from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping
from uuid import uuid4

from historymanager import HistoryManager
from historymanager.manager import isoformat_z
from nexus import DataPacket

from .bus_manager import BusManager
from .command_router import CommandRouter
from .device_registry import DeviceRegistry
from .health import BackendHealthMonitor, HealthPublisher
from .ipc_models import (
    IPCMessage,
    backend_status_message,
    command_result_message,
    device_inventory_message,
    error_message,
    hardware_status_message,
    hello_ack_message,
    operator_action_recorded_message,
    pong_message,
    run_status_message,
    script_status_message,
    state_snapshot_message,
    structured_event_message,
)
from .ipc_server import IPCServer
from .reducer import Reducer
from .run_controller import RunController
from .script_runner import ScriptRunner
from .state_store import StateStore
from .structured_builder import StructuredEventBuilder
from .telemetry_models import NormalizedTelemetryPacket


class BackendService:
    """Backend service skeleton."""

    def __init__(
        self,
        *,
        project_root: str | Path | None = None,
        socket_path: str | Path | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve() if project_root else None
        self.started_at = isoformat_z()
        self.service_name = "teststand-backend"

        self.history_manager = HistoryManager(project_root=project_root)
        self.health = HealthPublisher(history_manager=self.history_manager)

        self.state_store = StateStore(
            service_name=self.service_name,
            backend_started_at=self.started_at,
        )
        self.run_controller = RunController(
            history_manager=self.history_manager,
            state_store=self.state_store,
        )

        self.reducer = Reducer(state_store=self.state_store)
        self.structured_builder = StructuredEventBuilder()

        self.device_registry = DeviceRegistry()
        self.device_registry.set_packet_listener(self._handle_device_packet)
        self.device_registry.load_from_settings()
        self.state_store.set_device_inventory(
            devices=self.device_registry.get_gui_device_presentations(),
            load_errors=self.device_registry.get_load_errors(),
        )

        self.bus_manager = BusManager(
            auto_reconnect=True,
            reconnect_initial_delay=0.50,
            reconnect_max_delay=5.00,
            reconnect_backoff=2.00,
            receive_poll_interval=0.05,
            monitor_interval=0.50,
            max_receive_failures_before_reconnect=3,
        )

        self.bus_manager.set_event_callbacks(
            status_callback=self._handle_bus_status_event,
            packet_callback=self._handle_bus_packet_hook,
            error_callback=self._handle_bus_error_event,

        )
        self.command_router = CommandRouter(
            device_registry=self.device_registry,
            bus_manager=self.bus_manager,
            state_snapshot_getter=self.state_store.get_snapshot,
        )
        self.script_runner = ScriptRunner(
            command_dispatcher=self._dispatch_script_command,
            state_snapshot_getter=self.state_store.get_snapshot,
            progress_callback=self._handle_script_progress,
        )
        self.health_monitor = BackendHealthMonitor(
            history_manager=self.history_manager,
            state_store=self.state_store,
            health_publisher=self.health,
        )
        self.health_monitor.start()

        if socket_path is None:
            if self.project_root is None:
                socket_path = Path(".backend_service.sock").resolve()
            else:
                socket_path = self.project_root / ".backend_service.sock"

        self.socket_path = Path(socket_path).expanduser().resolve()

        self._lock = threading.RLock()
        self._connected_clients: set[str] = set()
        self._client_sessions_by_connection_id: dict[str, dict[str, Any]] = {}

        self.supported_messages = [
            "hello",
            "ping",
            "status_request",
            "request_full_state",
            "list_devices",
            "initialize_live_hardware",
            "shutdown_live_hardware",
            "start_run",
            "finish_run",
            "ingest_mock_telemetry",
            "operator_action",
            "command_request",
            "start_script",
            "stop_script",
            "hold_script",
            "continue_script",
        ]

        self.server = IPCServer(
            socket_path=self.socket_path,
            on_message=self.handle_message,
            on_client_connected=self.on_client_connected,
            on_client_disconnected=self.on_client_disconnected,
        )

    def serve_forever(self) -> None:
        self.server.serve_forever()

    def stop(self) -> None:
        if self.history_manager.is_running:
            self.health.record_system_event(
                "backend_stopping",
                severity="info",
            )

        self.script_runner.shutdown()

        self.bus_manager.shutdown_live_hardware()
        self.device_registry.clear_live_registration_flags()
        self.state_store.set_bus_connection_state(
            connected=False,
            reconnecting=False,
            wall_time=isoformat_z(),
            registered_ids=[],
            skipped_ids=[],
        )
        self.state_store.set_device_inventory(
            devices=self.device_registry.get_gui_device_presentations(),
            load_errors=self.device_registry.get_load_errors(),
        )
        try:
            self.health_monitor.sample_once()
        except Exception:
            pass

        self.server.stop()
        self.health_monitor.stop()

    def on_client_connected(self, client_id: str) -> None:
        with self._lock:
            self._connected_clients.add(client_id)
            connected_count = len(self._connected_clients)
            self.state_store.set_connected_clients(connected_count)

        self.health.record_system_event(
            "gui_client_connected",
            severity="info",
            connection_id=client_id,
            connected_clients=connected_count,
        )

    def on_client_disconnected(self, client_id: str) -> None:
        with self._lock:
            self._connected_clients.discard(client_id)
            session = self._client_sessions_by_connection_id.pop(client_id, None)
            connected_count = len(self._connected_clients)
            self.state_store.set_connected_clients(connected_count)

        disconnect_payload: dict[str, Any] = {
            "connection_id": client_id,
            "connected_clients": connected_count,
        }
        if session is not None:
            disconnect_payload.update(
                {
                    "logical_client_id": session.get("logical_client_id"),
                    "window_role": session.get("window_role"),
                    "session_id": session.get("session_id"),
                    "mode": session.get("mode"),
                    "window_kind": session.get("window_kind"),
                    "pid": session.get("pid"),
                    "launcher_pid": session.get("launcher_pid"),
                }
            )

        self.health.record_system_event(
            "gui_client_disconnected",
            severity="info",
            **disconnect_payload,
        )

    def handle_message(self, client_id: str, message: IPCMessage) -> Iterable[IPCMessage]:
        if message.type == "hello":
            client_session = self._register_client_hello(client_id, message.payload)

            self.health.record_system_event(
                "gui_client_hello",
                severity="info",
                connection_id=client_id,
                logical_client_id=client_session.get("logical_client_id"),
                window_role=client_session.get("window_role"),
                session_id=client_session.get("session_id"),
                mode=client_session.get("mode"),
                window_kind=client_session.get("window_kind"),
                pid=client_session.get("pid"),
                launcher_pid=client_session.get("launcher_pid"),
            )

            yield hello_ack_message(
                service_name=self.service_name,
                backend_started_at=self.started_at,
                connected_clients=self.connected_client_count,
                supported_messages=self.supported_messages,
                client_session=client_session,
                connected_client_sessions=self.connected_client_sessions,
            )
            yield self._build_backend_status_message()
            return

        if message.type == "ping":
            yield pong_message()
            return

        if message.type == "status_request":
            yield self._build_backend_status_message()
            return

        if message.type == "request_full_state":
            yield state_snapshot_message(self.state_store.get_snapshot())
            return

        if message.type == "list_devices":
            snapshot = self.state_store.get_snapshot()["device_registry"]
            yield device_inventory_message(
                total_devices=snapshot["total_devices"],
                load_error_count=snapshot["load_error_count"],
                load_errors=snapshot["load_errors"],
                devices=snapshot["devices"],
            )
            return

        if message.type == "initialize_live_hardware":
            try:
                result = self.bus_manager.initialize_live_hardware(self.device_registry)
            except Exception as exc:
                self.health.record_system_event(
                    "live_hardware_init_failed",
                    severity="error",
                    message=str(exc),
                )
                yield error_message("initialize_live_hardware_failed", str(exc))
                return

            self.state_store.set_bus_connection_state(
                connected=True,
                reconnecting=False,
                wall_time=isoformat_z(),
                sender=result.sender,
                bitrate=result.bitrate,
                registered_ids=result.registered_ids,
                skipped_ids=result.skipped_ids,
            )
            self.state_store.set_device_inventory(
                devices=self.device_registry.get_gui_device_presentations(),
                load_errors=self.device_registry.get_load_errors(),
            )

            self.health.record_system_event(
                "live_hardware_initialized",
                severity="info",
                sender=result.sender,
                bitrate=result.bitrate,
                registered_ids=list(result.registered_ids),
                skipped_ids=list(result.skipped_ids),
                registered_count=result.registered_count,
                skipped_count=result.skipped_count,
            )
            self.health_monitor.sample_once()

            yield hardware_status_message(
                connected=True,
                sender=result.sender,
                bitrate=result.bitrate,
                registered_ids=result.registered_ids,
                skipped_ids=result.skipped_ids,
            )
            yield state_snapshot_message(self.state_store.get_snapshot())
            return

        if message.type == "shutdown_live_hardware":
            self.bus_manager.shutdown_live_hardware()
            self.device_registry.clear_live_registration_flags()
            self.state_store.set_bus_connection_state(
                connected=False,
                reconnecting=False,
                wall_time=isoformat_z(),
                registered_ids=[],
                skipped_ids=[],
            )
            self.state_store.set_device_inventory(
                devices=self.device_registry.get_gui_device_presentations(),
                load_errors=self.device_registry.get_load_errors(),
            )

            self.health.record_system_event(
                "live_hardware_shutdown",
                severity="info",
                sender=self.bus_manager.sender,
                bitrate=self.bus_manager.bitrate,
            )
            self.health_monitor.sample_once()

            yield hardware_status_message(
                connected=False,
                sender=self.bus_manager.sender,
                bitrate=self.bus_manager.bitrate,
                registered_ids=[],
                skipped_ids=[],
            )
            yield state_snapshot_message(self.state_store.get_snapshot())
            return

        if message.type == "start_run":
            try:
                payload = self._normalize_mapping_payload(message.payload)
                test_name = self._require_non_empty_string(payload, "test_name")
                mode = self._get_optional_string(payload, "mode") or "live"
                run_result = self.run_controller.start_run(
                    test_name=test_name,
                    mode=mode,
                    run_id=self._get_optional_string(payload, "run_id"),
                    operator=self._get_optional_string(payload, "operator"),
                    profile_name=self._get_optional_string(payload, "profile_name"),
                    notes=self._get_optional_string(payload, "notes"),
                    software_git_commit=self._get_optional_string(payload, "software_git_commit"),
                    software_branch=self._get_optional_string(payload, "software_branch"),
                    device_map_version=self._get_optional_string(payload, "device_map_version"),
                    svg_version=self._get_optional_string(payload, "svg_version"),
                    bus_config=self._get_optional_mapping(payload, "bus_config"),
                    clock_info=self._get_optional_mapping(payload, "clock_info"),
                    extra_metadata=self._get_optional_mapping(payload, "extra_metadata"),
                )
            except Exception as exc:
                yield error_message("start_run_failed", str(exc))
                return

            self.health.record_system_event(
                "run_started",
                severity="info",
                run_id=run_result["run_id"],
                mode=run_result.get("mode"),
                test_name=run_result.get("test_name"),
                operator=run_result.get("operator"),
                profile_name=run_result.get("profile_name"),
            )
            self.health_monitor.sample_once()

            yield run_status_message(
                run_id=run_result["run_id"],
                mode=run_result.get("mode"),
                status=run_result["status"],
                test_name=run_result.get("test_name"),
                operator=run_result.get("operator"),
                profile_name=run_result.get("profile_name"),
                started_wall_time=run_result.get("started_wall_time"),
            )
            yield self._build_backend_status_message()
            yield state_snapshot_message(self.state_store.get_snapshot())
            return

        if message.type == "finish_run":
            try:
                payload = self._normalize_mapping_payload(message.payload)
                reason = self._get_optional_string(payload, "reason") or "operator_stop"

                current_run = self.history_manager.current_run
                current_run_id = current_run.run_id if current_run is not None else None

                if current_run_id is not None:
                    self.health.record_system_event(
                        "run_finish_requested",
                        severity="info",
                        run_id=current_run_id,
                        reason=reason,
                    )

                finish_result = self.run_controller.finish_run(reason=reason)
            except Exception as exc:
                yield error_message("finish_run_failed", str(exc))
                return

            self.health_monitor.sample_once()

            yield run_status_message(
                run_id=finish_result["run_id"],
                mode=finish_result.get("mode"),
                status=finish_result["status"],
                test_name=finish_result.get("test_name"),
                reason=finish_result.get("reason"),
                finished_wall_time=finish_result.get("finished_wall_time"),
            )
            yield self._build_backend_status_message()
            yield state_snapshot_message(self.state_store.get_snapshot())
            return

        if message.type == "ingest_mock_telemetry":
            try:
                payload = self._normalize_mapping_payload(message.payload)
                device_id = self._require_non_empty_string(payload, "device_id")

                if device_id not in self.device_registry:
                    raise ValueError(f"Unknown device_id: {device_id}")

                meta = self.device_registry.get_meta(device_id)
                runtime = self.device_registry.get_runtime(device_id)
                runtime_shadow = self._build_mock_runtime_shadow(runtime=runtime, payload=payload)

                seq = self._get_optional_int(payload, "seq") or 1
                cmd = self._get_optional_int(payload, "cmd") or 1
                reply = self._get_optional_bool(payload, "reply", default=True)
                err = self._get_optional_bool(payload, "err", default=False)
                rsvd = self._get_optional_bool(payload, "rsvd", default=False)
                data = self._get_optional_int_list(payload, "data") or [0, 0, 0, 0, 0, 0]

                packet = DataPacket(
                    id=meta["address"],
                    seq=seq,
                    cmd=cmd,
                    data=data,
                    reply=reply,
                    err=err,
                    rsvd=rsvd,
                )

                packet_timestamp = payload.get("packet_timestamp")
                if isinstance(packet_timestamp, (int, float)):
                    packet.timestamp = float(packet_timestamp)

                structured_event = self._process_telemetry_packet(
                    meta=meta,
                    runtime=runtime_shadow,
                    packet=packet,
                    source="mock_ipc",
                )
            except Exception as exc:
                yield error_message("ingest_mock_telemetry_failed", str(exc))
                return

            yield structured_event_message(structured_event)
            yield state_snapshot_message(self.state_store.get_snapshot())
            return

        if message.type == "operator_action":
            try:
                payload = self._normalize_mapping_payload(message.payload)
                action_event = self._build_operator_action_event(payload)
                self._record_operator_action_if_running(action_event)
            except Exception as exc:
                yield error_message("operator_action_failed", str(exc))
                return

            yield operator_action_recorded_message(action_event)
            return

        if message.type == "command_request":
            try:
                payload = self._normalize_mapping_payload(message.payload)
                dispatch_info = self._dispatch_script_command(payload)
            except Exception as exc:
                command_name = None
                device_id = None
                if isinstance(message.payload, Mapping):
                    command_name = message.payload.get("command_name")
                    device_id = message.payload.get("device_id")

                self.health.record_system_event(
                    "command_dispatch_failed",
                    severity="error",
                    message=str(exc),
                    command_name=command_name if isinstance(command_name, str) else None,
                    device_id=device_id if isinstance(device_id, str) else None,
                )

                yield command_result_message(
                    success=False,
                    command_name=command_name if isinstance(command_name, str) else "<unknown>",
                    device_id=device_id if isinstance(device_id, str) else None,
                    dispatched_via="none",
                    error=str(exc),
                    status="failed",
                    adapter_name="service_guard",
                )
                return

            yield command_result_message(
                success=bool(dispatch_info.get("success")),
                command_name=str(dispatch_info.get("command_name") or "<unknown>"),
                device_id=dispatch_info.get("device_id") if isinstance(dispatch_info.get("device_id"), str) else None,
                dispatched_via=str(dispatch_info.get("dispatched_via") or "none"),
                result_summary=dispatch_info.get("result_summary"),
                error=dispatch_info.get("error") if isinstance(dispatch_info.get("error"), str) else None,
                status=dispatch_info.get("status") if isinstance(dispatch_info.get("status"), str) else None,
                adapter_name=dispatch_info.get("adapter_name") if isinstance(dispatch_info.get("adapter_name"), str) else None,
                rejection_reason=dispatch_info.get("rejection_reason") if isinstance(dispatch_info.get("rejection_reason"), str) else None,
                interlock_reason=dispatch_info.get("interlock_reason") if isinstance(dispatch_info.get("interlock_reason"), str) else None,
                validation_errors=list(dispatch_info.get("validation_errors", [])) if isinstance(dispatch_info.get("validation_errors"), list) else None,
            )
            return

        if message.type == "start_script":
            try:
                payload = self._normalize_mapping_payload(message.payload)
                script_id = uuid4().hex

                start_result = self.script_runner.start_script(
                    payload,
                    script_id=script_id,
                    on_exit=self._handle_script_exit,
                )

                self.state_store.mark_script_started(
                    script_id=start_result.script_id,
                    name=start_result.name,
                    pid=start_result.pid,
                    launch_mode=start_result.launch_mode,
                    command=start_result.command,
                    cwd=start_result.cwd,
                    started_wall_time=isoformat_z(),
                    current_step_index=start_result.current_step_index,
                    total_steps=start_result.total_steps,
                    current_step_name=start_result.current_step_name,
                    current_step_type=start_result.current_step_type,
                    current_step_status=start_result.current_step_status,
                    plan_steps_summary=start_result.plan_steps_summary,
                    is_held=False,
                    hold_requested=False,
                )

                self.health.record_system_event(
                    "script_started",
                    severity="info",
                    script_id=start_result.script_id,
                    name=start_result.name,
                    pid=start_result.pid,
                    launch_mode=start_result.launch_mode,
                    command=list(start_result.command),
                    cwd=start_result.cwd,
                )
            except Exception as exc:
                self.health.record_system_event(
                    "script_start_failed",
                    severity="error",
                    message=str(exc),
                )
                yield error_message("start_script_failed", str(exc))
                return

            self.health_monitor.sample_once()

            yield script_status_message(
                status="started",
                script_id=start_result.script_id,
                name=start_result.name,
                pid=start_result.pid,
                launch_mode=start_result.launch_mode,
                command=start_result.command,
                cwd=start_result.cwd,
                current_step_index=start_result.current_step_index,
                total_steps=start_result.total_steps,
                current_step_name=start_result.current_step_name,
                current_step_type=start_result.current_step_type,
                current_step_status=start_result.current_step_status,
                plan_steps_summary=start_result.plan_steps_summary,
                is_held=False,
                hold_requested=False,
            )
            yield state_snapshot_message(self.state_store.get_snapshot())
            return

        if message.type == "stop_script":
            try:
                payload = self._normalize_mapping_payload(message.payload)
                reason = self._get_optional_string(payload, "reason") or "operator_stop"

                stop_result = self.script_runner.stop_script(reason=reason)
                self.state_store.mark_script_finished(
                    finished_wall_time=isoformat_z(),
                    return_code=stop_result.get("returncode"),
                    reason=reason,
                )
                self.state_store.clear_script_running_state()

                self.health.record_system_event(
                    "script_stopped",
                    severity="info",
                    script_id=stop_result.get("script_id"),
                    name=stop_result.get("name"),
                    pid=stop_result.get("pid"),
                    reason=reason,
                    returncode=stop_result.get("returncode"),
                    stopped_via=stop_result.get("stopped_via"),
                )
            except Exception as exc:
                self.health.record_system_event(
                    "script_stop_failed",
                    severity="error",
                    message=str(exc),
                )
                yield error_message("stop_script_failed", str(exc))
                return

            self.health_monitor.sample_once()

            yield script_status_message(
                status="stopped",
                script_id=stop_result.get("script_id"),
                name=stop_result.get("name"),
                pid=stop_result.get("pid"),
                returncode=stop_result.get("returncode"),
                reason=reason,
                is_held=False,
                hold_requested=False,
            )
            yield state_snapshot_message(self.state_store.get_snapshot())
            return

        if message.type == "hold_script":
            try:
                payload = self._normalize_mapping_payload(message.payload)
                reason = self._get_optional_string(payload, "reason") or "operator_hold"
                hold_result = self.script_runner.hold_script(reason=reason)
                wall_time = isoformat_z()

                if hold_result.get("status") == "held":
                    self.state_store.mark_script_held(
                        wall_time=wall_time,
                        current_step_index=hold_result.get("current_step_index"),
                        total_steps=hold_result.get("total_steps"),
                        current_step_name=hold_result.get("current_step_name"),
                        current_step_type=hold_result.get("current_step_type"),
                    )
                    self.health.record_system_event(
                        "script_held",
                        severity="info",
                        script_id=hold_result.get("script_id"),
                        name=hold_result.get("name"),
                        pid=hold_result.get("pid"),
                        reason=reason,
                        current_step_index=hold_result.get("current_step_index"),
                        current_step_name=hold_result.get("current_step_name"),
                        current_step_type=hold_result.get("current_step_type"),
                    )
                else:
                    self.state_store.mark_script_hold_requested(
                        wall_time=wall_time,
                        current_step_index=hold_result.get("current_step_index"),
                        total_steps=hold_result.get("total_steps"),
                        current_step_name=hold_result.get("current_step_name"),
                        current_step_type=hold_result.get("current_step_type"),
                    )
                    self.health.record_system_event(
                        "script_hold_requested",
                        severity="info",
                        script_id=hold_result.get("script_id"),
                        name=hold_result.get("name"),
                        pid=hold_result.get("pid"),
                        reason=reason,
                        current_step_index=hold_result.get("current_step_index"),
                        current_step_name=hold_result.get("current_step_name"),
                        current_step_type=hold_result.get("current_step_type"),
                    )
            except Exception as exc:
                self.health.record_system_event(
                    "script_hold_failed",
                    severity="error",
                    message=str(exc),
                )
                yield error_message("hold_script_failed", str(exc))
                return

            self.health_monitor.sample_once()

            yield script_status_message(
                status=hold_result.get("status", "hold_requested"),
                script_id=hold_result.get("script_id"),
                name=hold_result.get("name"),
                pid=hold_result.get("pid"),
                launch_mode=hold_result.get("launch_mode"),
                reason=reason,
                current_step_index=hold_result.get("current_step_index"),
                total_steps=hold_result.get("total_steps"),
                current_step_name=hold_result.get("current_step_name"),
                current_step_type=hold_result.get("current_step_type"),
                current_step_status=hold_result.get("current_step_status"),
                plan_steps_summary=hold_result.get("plan_steps_summary"),
                is_held=hold_result.get("is_held"),
                hold_requested=hold_result.get("hold_requested"),
            )
            yield state_snapshot_message(self.state_store.get_snapshot())
            return

        if message.type == "continue_script":
            try:
                payload = self._normalize_mapping_payload(message.payload)
                reason = self._get_optional_string(payload, "reason") or "operator_continue"
                continue_result = self.script_runner.continue_script(reason=reason)
                wall_time = isoformat_z()

                self.state_store.mark_script_continued(
                    wall_time=wall_time,
                    current_step_index=continue_result.get("current_step_index"),
                    total_steps=continue_result.get("total_steps"),
                    current_step_name=continue_result.get("current_step_name"),
                    current_step_type=continue_result.get("current_step_type"),
                )
                self.health.record_system_event(
                    "script_continued",
                    severity="info",
                    script_id=continue_result.get("script_id"),
                    name=continue_result.get("name"),
                    pid=continue_result.get("pid"),
                    reason=reason,
                    current_step_index=continue_result.get("current_step_index"),
                    current_step_name=continue_result.get("current_step_name"),
                    current_step_type=continue_result.get("current_step_type"),
                )
            except Exception as exc:
                self.health.record_system_event(
                    "script_continue_failed",
                    severity="error",
                    message=str(exc),
                )
                yield error_message("continue_script_failed", str(exc))
                return

            self.health_monitor.sample_once()

            yield script_status_message(
                status=continue_result.get("status", "continued"),
                script_id=continue_result.get("script_id"),
                name=continue_result.get("name"),
                pid=continue_result.get("pid"),
                launch_mode=continue_result.get("launch_mode"),
                reason=reason,
                current_step_index=continue_result.get("current_step_index"),
                total_steps=continue_result.get("total_steps"),
                current_step_name=continue_result.get("current_step_name"),
                current_step_type=continue_result.get("current_step_type"),
                current_step_status=continue_result.get("current_step_status"),
                plan_steps_summary=continue_result.get("plan_steps_summary"),
                is_held=continue_result.get("is_held"),
                hold_requested=continue_result.get("hold_requested"),
            )
            yield state_snapshot_message(self.state_store.get_snapshot())
            return

        yield error_message(
            "unsupported_message_type",
            f"Unsupported IPC message type: {message.type}",
        )

    @property
    def connected_client_count(self) -> int:
        with self._lock:
            return len(self._connected_clients)

    @property
    def connected_client_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            sessions = [dict(session) for session in self._client_sessions_by_connection_id.values()]

        sessions.sort(
            key=lambda session: (
                str(session.get("window_role") or ""),
                str(session.get("logical_client_id") or ""),
                str(session.get("connection_id") or ""),
            )
        )
        return sessions

    def _dispatch_script_command(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_mapping_payload(payload)
        operator_action_payload = self._get_optional_mapping(normalized, "operator_action")
        if operator_action_payload is not None:
            action_event = self._build_operator_action_event(operator_action_payload)
            self._record_operator_action_if_running(action_event)

        dispatch_result = self.command_router.route_command(normalized)

        if dispatch_result.success and dispatch_result.command_event is not None:
            self._record_command_out_if_running(
                dispatch_result.command_event,
                result_summary=dispatch_result.result_summary,
            )
        elif dispatch_result.status == "rejected":
            self.health.record_system_event(
                "command_rejected",
                severity="warning",
                command_name=dispatch_result.command_name,
                device_id=dispatch_result.device_id,
                adapter_name=dispatch_result.adapter_name,
                rejection_reason=dispatch_result.rejection_reason,
                interlock_reason=dispatch_result.interlock_reason,
                validation_errors=list(dispatch_result.validation_errors),
            )
        elif dispatch_result.status == "failed":
            self.health.record_system_event(
                "command_dispatch_failed",
                severity="error",
                command_name=dispatch_result.command_name,
                device_id=dispatch_result.device_id,
                adapter_name=dispatch_result.adapter_name,
                message=dispatch_result.error,
            )

        return {
            "success": dispatch_result.success,
            "status": dispatch_result.status,
            "command_name": dispatch_result.command_name,
            "device_id": dispatch_result.device_id,
            "dispatched_via": dispatch_result.dispatched_via,
            "adapter_name": dispatch_result.adapter_name,
            "result_summary": dispatch_result.result_summary,
            "rejection_reason": dispatch_result.rejection_reason,
            "interlock_reason": dispatch_result.interlock_reason,
            "validation_errors": list(dispatch_result.validation_errors),
            "error": dispatch_result.error,
        }

    def _handle_script_progress(self, info: Mapping[str, Any]) -> None:
        progress_wall_time = info.get("progress_wall_time")
        if not isinstance(progress_wall_time, str) or not progress_wall_time.strip():
            progress_wall_time = isoformat_z()

        self.state_store.update_script_progress(
            current_step_index=info.get("current_step_index") if isinstance(info.get("current_step_index"), int) else None,
            total_steps=info.get("total_steps") if isinstance(info.get("total_steps"), int) else None,
            current_step_name=info.get("current_step_name") if isinstance(info.get("current_step_name"), str) else None,
            current_step_type=info.get("current_step_type") if isinstance(info.get("current_step_type"), str) else None,
            current_step_status=info.get("current_step_status") if isinstance(info.get("current_step_status"), str) else None,
            progress_wall_time=progress_wall_time,
            plan_steps_summary=list(info.get("plan_steps_summary", [])) if isinstance(info.get("plan_steps_summary"), list) else None,
            is_held=bool(info.get("is_held")) if info.get("is_held") is not None else None,
            hold_requested=bool(info.get("hold_requested")) if info.get("hold_requested") is not None else None,
        )
        self.health_monitor.sample_once()

    def _handle_device_packet(self, meta: dict[str, Any], runtime: Any, packet: Any) -> None:
        self._process_telemetry_packet(
            meta=meta,
            runtime=runtime,
            packet=packet,
            source="bus",
        )

    def _handle_bus_status_event(self, event: Mapping[str, Any]) -> None:
        event_name = str(event.get("event") or "unknown")
        reason = event.get("reason")
        sender = event.get("sender") if isinstance(event.get("sender"), str) else self.bus_manager.sender
        bitrate = event.get("bitrate") if isinstance(event.get("bitrate"), int) else self.bus_manager.bitrate
        registered_ids = list(event.get("registered_ids", [])) if isinstance(event.get("registered_ids"), list) else None
        skipped_ids = list(event.get("skipped_ids", [])) if isinstance(event.get("skipped_ids"), list) else None
        wall_time = isoformat_z()

        if event_name == "connected":
            if reason == "initial_connect":
                return

            self.state_store.set_bus_connection_state(
                connected=True,
                reconnecting=False,
                wall_time=wall_time,
                sender=sender,
                bitrate=bitrate,
                registered_ids=registered_ids,
                skipped_ids=skipped_ids,
            )
            self.state_store.set_device_inventory(
                devices=self.device_registry.get_gui_device_presentations(),
                load_errors=self.device_registry.get_load_errors(),
            )
            self.health.record_system_event(
                "bus_reconnected",
                severity="info",
                sender=sender,
                bitrate=bitrate,
                registered_ids=registered_ids or [],
                skipped_ids=skipped_ids or [],
            )
            self.health_monitor.sample_once()
            return

        if event_name == "reconnecting":
            self.state_store.set_bus_connection_state(
                connected=False,
                reconnecting=True,
                wall_time=wall_time,
                sender=sender,
                bitrate=bitrate,
            )
            self.health.record_system_event(
                "bus_reconnecting",
                severity="warning",
                sender=sender,
                bitrate=bitrate,
                delay_seconds=event.get("delay_seconds"),
            )
            self.health_monitor.sample_once()
            return

        if event_name == "disconnected":
            if reason == "manual_shutdown":
                return

            self.state_store.set_bus_connection_state(
                connected=False,
                reconnecting=self.bus_manager.auto_reconnect,
                wall_time=wall_time,
                sender=sender,
                bitrate=bitrate,
            )
            self.health.record_system_event(
                "bus_disconnected",
                severity="warning",
                sender=sender,
                bitrate=bitrate,
                reason=reason,
            )
            self.health_monitor.sample_once()
            return

        if event_name in {"receive_loop_started", "receive_loop_stopped", "packet_listener_attached"}:
            self.health.record_system_event(
                f"bus_{event_name}",
                severity="info",
                **dict(event),
            )
            self.health_monitor.sample_once()

    def _handle_bus_packet_hook(self, packet: Any) -> None:
        """Reserved bus-level packet hook.

        The authoritative live telemetry path still comes from device runtime
        callbacks installed by ``DeviceRegistry``. This hook stays available for a
        later packet-only fanout path once bus-level decode rules are ready.
        """

    def _build_mock_runtime_shadow(
        self,
        *,
        runtime: Any,
        payload: Mapping[str, Any],
    ) -> Any:
        return SimpleNamespace(
            value=payload.get("runtime_value", getattr(runtime, "value", None)),
            aux=payload.get("runtime_aux", getattr(runtime, "aux", None)),
            time=payload.get("runtime_time", getattr(runtime, "time", None)),
            state=payload.get("runtime_state", getattr(runtime, "state", None)),
            position=payload.get("runtime_position", getattr(runtime, "position", None)),
            status=payload.get("runtime_status", getattr(runtime, "status", None)),
        )

    def _handle_bus_error_event(self, event: Mapping[str, Any]) -> None:
        payload = dict(event)
        error_type = str(payload.pop("error_type", "bus_manager_error"))
        message = payload.pop("message", "bus manager error")
        self.health.record_system_event(
            error_type,
            severity="error",
            message=message,
            **payload,
        )
        self.health_monitor.sample_once()


    def _handle_script_exit(self, info: Mapping[str, Any]) -> None:
        returncode = info.get("returncode")
        self.state_store.mark_script_finished(
            finished_wall_time=isoformat_z(),
            return_code=returncode if isinstance(returncode, int) else None,
            reason="process_exit",
        )
        self.state_store.clear_script_running_state()

        self.health.record_system_event(
            "script_exited",
            severity="info" if returncode == 0 else "warning",
            script_id=info.get("script_id"),
            name=info.get("name"),
            pid=info.get("pid"),
            launch_mode=info.get("launch_mode"),
            command=list(info.get("command", [])),
            cwd=info.get("cwd"),
            returncode=returncode,
            current_step_index=info.get("current_step_index"),
            total_steps=info.get("total_steps"),
            current_step_name=info.get("current_step_name"),
            current_step_type=info.get("current_step_type"),
            current_step_status=info.get("current_step_status"),
            failure_message=info.get("failure_message"),
            is_held=info.get("is_held"),
            hold_requested=info.get("hold_requested"),
        )
        self.health_monitor.sample_once()

    def _process_telemetry_packet(
        self,
        *,
        meta: dict[str, Any],
        runtime: Any,
        packet: Any,
        source: str,
    ) -> dict[str, Any]:
        telemetry = NormalizedTelemetryPacket.from_meta_runtime_packet(
            meta=meta,
            runtime=runtime,
            packet=packet,
            source=source,
        )

        raw_event = self.structured_builder.build_raw_telemetry_event(
            telemetry=telemetry,
        )

        if self.history_manager.is_running:
            self.history_manager.record_raw_event("telemetry_in", raw_event)

        reduction = self.reducer.apply_normalized_telemetry(
            telemetry=telemetry,
        )

        structured_event = self.structured_builder.build_structured_telemetry_event(
            telemetry=telemetry,
            reduction=reduction,
            first_order_event=raw_event,
        )

        if self.history_manager.is_running:
            self.history_manager.record_structured_event(
                "telemetry_in",
                structured_event,
            )

        return structured_event

    def _record_operator_action_if_running(self, action_event: Mapping[str, Any]) -> None:
        if self.history_manager.is_running:
            self.history_manager.record_raw_event("operator_action", action_event)

            structured_event = {
                **dict(action_event),
                "structured_at": isoformat_z(),
            }
            self.history_manager.record_structured_event(
                "operator_action",
                structured_event,
            )

    def _record_command_out_if_running(
        self,
        command_event: Mapping[str, Any],
        *,
        result_summary: Any = None,
    ) -> None:
        if self.history_manager.is_running:
            self.history_manager.record_raw_event("command_out", command_event)

            structured_event = {
                **dict(command_event),
                "event_kind": "command_out",
                "structured_at": isoformat_z(),
                "result_summary": result_summary,
            }
            self.history_manager.record_structured_event(
                "command_out",
                structured_event,
            )

    def _build_operator_action_event(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        action = self._require_non_empty_string(payload, "action")
        event = {
            "event_kind": "operator_action",
            "action": action,
            "recorded_by": "backend",
            "operator_action_at": isoformat_z(),
        }

        for key, value in payload.items():
            if key == "action":
                continue
            event[key] = value

        return event

    def _build_backend_status_message(self) -> IPCMessage:
        status = self.state_store.get_backend_status()
        return backend_status_message(
            backend_started_at=status["backend_started_at"],
            connected_clients=status["connected_clients"],
            active_run_id=status["active_run_id"],
            is_running=status["is_running"],
            connected_client_sessions=self.connected_client_sessions,
            health_summary=status.get("health_summary"),
        )

    def _register_client_hello(self, connection_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_client_session(connection_id, payload)

        with self._lock:
            previous = self._client_sessions_by_connection_id.get(connection_id)
            if previous is not None:
                normalized["connected_at"] = previous.get("connected_at") or normalized["connected_at"]
            self._client_sessions_by_connection_id[connection_id] = dict(normalized)

        return dict(normalized)

    def _normalize_client_session(self, connection_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        client_name = self._get_optional_string(payload, "client_name") or "user-gui"
        logical_client_id = self._get_optional_string(payload, "logical_client_id") or f"gui:{connection_id}"
        window_role = self._get_optional_string(payload, "window_role")
        session_id = self._get_optional_string(payload, "session_id") or connection_id
        mode = self._get_optional_string(payload, "mode")
        window_kind = self._get_optional_string(payload, "window_kind")
        selected_test = self._get_optional_string(payload, "selected_test")
        pid = self._get_optional_int(payload, "pid")
        launcher_pid = self._get_optional_int(payload, "launcher_pid")
        wall_time = isoformat_z()

        return {
            "connection_id": connection_id,
            "client_name": client_name,
            "logical_client_id": logical_client_id,
            "window_role": window_role,
            "session_id": session_id,
            "mode": mode,
            "window_kind": window_kind,
            "selected_test": selected_test,
            "pid": pid,
            "launcher_pid": launcher_pid,
            "connected_at": wall_time,
            "last_hello_wall_time": wall_time,
        }

    def _normalize_mapping_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return dict(payload)

    def _require_non_empty_string(self, payload: Mapping[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"IPC payload must include a non-empty string '{key}'")
        return value.strip()

    def _get_optional_string(self, payload: Mapping[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"IPC payload field '{key}' must be a string when provided")
        stripped = value.strip()
        return stripped or None

    def _get_optional_mapping(self, payload: Mapping[str, Any], key: str) -> dict[str, Any] | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError(f"IPC payload field '{key}' must be an object when provided")
        return dict(value)

    def _get_optional_int(self, payload: Mapping[str, Any], key: str) -> int | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, int):
            raise ValueError(f"IPC payload field '{key}' must be an integer when provided")
        return int(value)

    def _get_optional_bool(
        self,
        payload: Mapping[str, Any],
        key: str,
        *,
        default: bool | None = None,
    ) -> bool | None:
        value = payload.get(key, default)
        if value is None:
            return None
        if not isinstance(value, bool):
            raise ValueError(f"IPC payload field '{key}' must be a boolean when provided")
        return value

    def _get_optional_int_list(self, payload: Mapping[str, Any], key: str) -> list[int] | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError(f"IPC payload field '{key}' must be a list when provided")
        result: list[int] = []
        for item in value:
            if not isinstance(item, int):
                raise ValueError(f"IPC payload field '{key}' must contain integers only")
            if item < 0 or item > 255:
                raise ValueError(f"IPC payload field '{key}' integers must be 0..255")
            result.append(int(item))
        return result
