from __future__ import annotations

import logging
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping
from uuid import uuid4

import settings
from historymanager import HistoryManager
from historymanager.manager import isoformat_z
from nexus import DataPacket
from .gateway_bus_proxy import GatewayBusProxy
from .gateway_client import GatewayClient
from .bus_manager import BusManager
from .abort_command import (
    build_abort_dispatch_info,
    build_abort_structured_event,
    is_abort_command_payload,
    record_abort_system_event,
)
from .clear_abort_latch_command import (
    build_clear_abort_latch_dispatch_info,
    build_clear_abort_latch_structured_event,
    is_clear_abort_latch_command_payload,
    record_clear_abort_latch_system_event,
)
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

log = logging.getLogger(__name__)


class BackendService:
    """Backend service skeleton."""

    def __init__(
        self,
        *,
        project_root: str | Path | None = None,
        socket_path: str | Path | None = None,
        gateway_socket_path: str | Path | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve() if project_root else None
        self.started_at = isoformat_z()
        self.service_name = "teststand-backend"

        self.history_manager = HistoryManager(
            project_root=project_root,
            enable_raw_writer=False,
            enable_rawbak_writer=False,
            enable_structured_writer=True,
        )
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


        self.gateway_client = GatewayClient(
            project_root=self.project_root,
            socket_path=gateway_socket_path,
        )
        self.use_gateway_for_live_ingest = True
        self._gateway_last_registered_ids: list[str] = []
        self._gateway_last_skipped_ids: list[str] = []
        self._gateway_bus_proxies_by_id: dict[str, GatewayBusProxy] = {}
        self.health.set_raw_mirror_callback(self._mirror_raw_event_to_gateway)
        self._orphaned_gateway_raw_run: dict[str, Any] | None = None

        self.command_router = CommandRouter(
            device_registry=self.device_registry,
            bus_manager=self.bus_manager,
            state_snapshot_getter=self.state_store.get_snapshot,
        )
        self.script_runner = ScriptRunner(
            command_dispatcher=self._dispatch_script_command,
            abort_dispatcher=self._dispatch_script_abort,
            state_snapshot_getter=self.state_store.get_snapshot,
            progress_callback=self._handle_script_progress,
            output_callback=self._handle_script_output,
            project_root=self.project_root,
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
        self._live_startup_state_applied = False

        self.supported_messages = [
            "hello",
            "ping",
            "status_request",
            "request_full_state",
            "list_devices",
            "initialize_live_hardware",
            "shutdown_live_hardware",
            "gateway_hardware_status",
            "start_run",
            "finish_run",
            "ingest_mock_telemetry",
            "ingest_live_telemetry",
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

        try:
            self.gateway_client.close()
        except Exception:
            log.exception("Backend failed to close gateway IPC client cleanly")

        if not self.use_gateway_for_live_ingest:
            self.bus_manager.shutdown_live_hardware()

        self._detach_all_gateway_bus_proxies()
        self._clear_orphaned_gateway_raw_run()

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
        self.health_monitor.sample_once()

    def on_client_disconnected(self, client_id: str) -> None:
        with self._lock:
            self._connected_clients.discard(client_id)
            session = self._client_sessions_by_connection_id.pop(client_id, None)
            connected_count = len(self._connected_clients)
            self.state_store.set_connected_clients(connected_count)
            self.state_store.remove_gui_client_session(connection_id=client_id)

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
        self.health_monitor.sample_once()

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

        self._touch_client_session(client_id, message.type, is_ping=message.type == "ping")

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
                if self.use_gateway_for_live_ingest:
                    hardware_payload = self._initialize_live_hardware_via_gateway()
                else:
                    hardware_payload = self._initialize_live_hardware_locally()
            except Exception as exc:
                self.health.record_system_event(
                    "live_hardware_init_failed",
                    severity="error",
                    message=str(exc),
                )
                yield error_message("initialize_live_hardware_failed", str(exc))
                return

            yield hardware_status_message(
                connected=bool(hardware_payload.get("connected", False)),
                sender=hardware_payload.get("sender"),
                bitrate=hardware_payload.get("bitrate"),
                registered_ids=list(hardware_payload.get("registered_ids") or []),
                skipped_ids=list(hardware_payload.get("skipped_ids") or []),
            )
            yield state_snapshot_message(self.state_store.get_snapshot())
            return

        if message.type == "shutdown_live_hardware":
            try:
                if self.use_gateway_for_live_ingest:
                    hardware_payload = self._shutdown_live_hardware_via_gateway()
                else:
                    hardware_payload = self._shutdown_live_hardware_locally()
            except Exception as exc:
                yield error_message("shutdown_live_hardware_failed", str(exc))
                return

            yield hardware_status_message(
                connected=bool(hardware_payload.get("connected", False)),
                sender=hardware_payload.get("sender"),
                bitrate=hardware_payload.get("bitrate"),
                registered_ids=list(hardware_payload.get("registered_ids") or []),
                skipped_ids=list(hardware_payload.get("skipped_ids") or []),
            )
            yield state_snapshot_message(self.state_store.get_snapshot())
            return

        if message.type == "gateway_hardware_status":
            try:
                payload = self._normalize_mapping_payload(message.payload)
                self._apply_gateway_hardware_status(payload, record_health=False)
            except Exception as exc:
                yield error_message("gateway_hardware_status_failed", str(exc))
                return

            yield state_snapshot_message(self.state_store.get_snapshot())
            return

        if message.type == "start_run":
            try:
                payload = self._normalize_mapping_payload(message.payload)
                test_name = self._require_non_empty_string(payload, "test_name")
                mode = self._get_optional_string(payload, "mode") or "live"

                orphaned = self._orphaned_gateway_raw_run
                if orphaned is not None:
                    orphan_run_id = str(orphaned.get("raw_run_id") or "")
                    orphan_test_name = str(orphaned.get("raw_test_name") or "")
                    raise RuntimeError(
                        "Cannot start a new run while an orphaned gateway raw run "
                        f"is still active (run_id={orphan_run_id}, "
                        f"test_name={orphan_test_name}). "
                        "Finish that run first."
                    )

                run_result = self.run_controller.start_run(
                    test_name=test_name,
                    mode=mode,
                    run_id=self._get_optional_string(payload, "run_id"),
                    operator=self._get_optional_string(payload, "operator"),
                    profile_name=self._get_optional_string(payload, "profile_name"),
                    notes=self._get_optional_string(payload, "notes"),
                    software_git_commit=self._get_optional_string(
                        payload,
                        "software_git_commit",
                    ),
                    software_branch=self._get_optional_string(
                        payload,
                        "software_branch",
                    ),
                    device_map_version=self._get_optional_string(
                        payload,
                        "device_map_version",
                    ),
                    svg_version=self._get_optional_string(payload, "svg_version"),
                    bus_config=self._get_optional_mapping(payload, "bus_config"),
                    clock_info=self._get_optional_mapping(payload, "clock_info"),
                    extra_metadata=self._get_optional_mapping(
                        payload,
                        "extra_metadata",
                    ),
                )

            except Exception as exc:
                yield error_message("start_run_failed", str(exc))
                return

            try:
                self._start_gateway_raw_run(
                    run_result=run_result,
                    original_payload=payload,
                )
            except Exception as exc:
                log.warning(
                    "Gateway raw run start failed (non-fatal, structured run continues): %s",
                    exc,
                )

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

                if current_run is None and self._orphaned_gateway_raw_run is not None:
                    finish_result = self._finish_orphaned_gateway_raw_run(reason=reason)

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

                if current_run_id is not None:
                    self.health.record_system_event(
                        "run_finish_requested",
                        severity="info",
                        run_id=current_run_id,
                        reason=reason,
                    )

                finish_result = self.run_controller.finish_run(reason=reason)

                if current_run_id is not None:
                    self._finish_gateway_raw_run(
                        run_id=current_run_id,
                        reason=reason,
                    )

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
                structured_event = self._ingest_mock_telemetry(message.payload)
            except Exception as exc:
                yield error_message("ingest_mock_telemetry_failed", str(exc))
                return

            yield structured_event_message(structured_event)
            yield state_snapshot_message(self.state_store.get_snapshot())
            return

        if message.type == "ingest_live_telemetry":
            try:
                structured_event = self._ingest_live_telemetry(message.payload)
            except Exception as exc:
                yield error_message("ingest_live_telemetry_failed", str(exc))
                return

            yield structured_event_message(structured_event)
            yield state_snapshot_message(self.state_store.get_snapshot())
            return

        if message.type == "operator_action":
            try:
                payload = self._normalize_mapping_payload(message.payload)
                action_event = self._build_operator_action_event(payload)

                mirrored_action_event = self._mirror_operator_action_to_gateway_if_running(
                    action_event
                )
                if mirrored_action_event is not None:
                    action_event = mirrored_action_event

                self._record_operator_action_if_running(action_event)
            except Exception as exc:
                yield error_message("operator_action_failed", str(exc))
                return

            yield operator_action_recorded_message(action_event)
            return

        if message.type == "command_request":
            abort_system_event = None
            clear_abort_latch_system_event = None
            try:
                payload = self._normalize_mapping_payload(message.payload)
                if is_abort_command_payload(payload):
                    dispatch_info = build_abort_dispatch_info(
                        payload,
                        default_request_source="gui",
                    )
                    abort_system_event = build_abort_structured_event(dispatch_info)
                    record_abort_system_event(
                        self.health,
                        dispatch_info,
                        current_run_id=(
                            self.history_manager.current_run.run_id
                            if self.history_manager.current_run is not None
                            else None
                        ),
                    )
                    legacy_abort_message = dispatch_info.get("legacy_abort_message")
                    if isinstance(legacy_abort_message, str):
                        log.warning("%s", legacy_abort_message)
                elif is_clear_abort_latch_command_payload(payload):
                    dispatch_info = build_clear_abort_latch_dispatch_info(
                        payload,
                        default_request_source="gui",
                    )
                    clear_abort_latch_system_event = build_clear_abort_latch_structured_event(dispatch_info)
                    record_clear_abort_latch_system_event(
                        self.health,
                        dispatch_info,
                        current_run_id=(
                            self.history_manager.current_run.run_id
                            if self.history_manager.current_run is not None
                            else None
                        ),
                    )
                    self._reset_runtime_after_clear_abort_latch(dispatch_info)
                    legacy_clear_message = dispatch_info.get("legacy_clear_message")
                    if isinstance(legacy_clear_message, str):
                        log.warning("%s", legacy_clear_message)
                else:
                    dispatch_info = self._dispatch_command_request(
                        payload,
                        default_request_source="gui",
                    )
            except Exception as exc:
                command_name = None
                device_id = None
                request_id = None
                if isinstance(message.payload, Mapping):
                    command_name = message.payload.get("command_name")
                    device_id = message.payload.get("device_id")
                    request_id = message.payload.get("request_id")

                self.health.record_system_event(
                    "command_dispatch_failed",
                    severity="error",
                    message=str(exc),
                    command_name=command_name if isinstance(command_name, str) else None,
                    device_id=device_id if isinstance(device_id, str) else None,
                    request_id=request_id if isinstance(request_id, str) else None,
                )

                yield command_result_message(
                    success=False,
                    command_name=command_name if isinstance(command_name, str) else "<unknown>",
                    device_id=device_id if isinstance(device_id, str) else None,
                    dispatched_via="none",
                    error=str(exc),
                    status="failed",
                    adapter_name="service_guard",
                    request_id=request_id if isinstance(request_id, str) else None,
                )
                #yield state_snapshot_message(self.state_store.get_snapshot())
                return

            if abort_system_event is not None:
                yield structured_event_message(abort_system_event)

            if clear_abort_latch_system_event is not None:
                yield structured_event_message(clear_abort_latch_system_event)

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
                state_reasons=list(dispatch_info.get("state_reasons", [])) if isinstance(dispatch_info.get("state_reasons"), list) else None,
                request_id=dispatch_info.get("request_id") if isinstance(dispatch_info.get("request_id"), str) else None,
                request_source=dispatch_info.get("request_source") if isinstance(dispatch_info.get("request_source"), str) else None,
                authority_level=dispatch_info.get("authority_level") if isinstance(dispatch_info.get("authority_level"), str) else None,
                run_mode=dispatch_info.get("run_mode") if isinstance(dispatch_info.get("run_mode"), str) else None,
                requested_at=dispatch_info.get("requested_at") if isinstance(dispatch_info.get("requested_at"), str) else None,
            )
            #yield state_snapshot_message(self.state_store.get_snapshot())
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
                log.info("IPC stop_script: client_id=%s, reason=%r", client_id, reason)

                stop_result = self.script_runner.stop_script(reason=reason)
                self.state_store.mark_script_finished(
                    finished_wall_time=isoformat_z(),
                    return_code=stop_result.get("returncode"),
                    reason=reason,
                    exit_status="stopped",
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

        if message.type == "shutdown_service":
            self.health.record_system_event(
                "backend_shutdown_requested",
                severity="warning",
                message="Backend service shutdown requested by GUI client",
            )
            # Stop the IPC server to break out of serve_forever()
            self.server.stop()
            # Yield acknowledgment before shutting down
            yield pong_message()
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

    def _build_device_inventory_with_live_registration(
        self,
        registered_ids: Iterable[str],
    ) -> list[dict[str, Any]]:
        registered = {str(device_id) for device_id in registered_ids}
        devices = self.device_registry.get_gui_device_presentations()
        for device in devices:
            device["live_registered"] = str(device.get("id") or "") in registered
        return devices

    def _apply_gateway_hardware_status(
        self,
        payload: Mapping[str, Any],
        *,
        record_health: bool,
    ) -> dict[str, Any]:
        normalized = self._normalize_mapping_payload(payload)

        connected = bool(normalized.get("connected", False))
        reconnecting = bool(normalized.get("reconnecting", False))
        status = self._get_optional_string(normalized, "status") or (
            "connected" if connected else "disconnected"
        )
        sender = self._get_optional_string(normalized, "sender") or self.bus_manager.sender
        bitrate = self._get_optional_int(normalized, "bitrate") or self.bus_manager.bitrate
        registered_ids = [str(x) for x in (normalized.get("registered_ids") or [])]
        skipped_ids = [str(x) for x in (normalized.get("skipped_ids") or [])]
        wall_time = self._get_optional_string(normalized, "wall_time") or isoformat_z()

        self._gateway_last_registered_ids = list(registered_ids)
        self._gateway_last_skipped_ids = list(skipped_ids)

        registered_set = set(registered_ids)

        # Keep runtime.live_registered in sync with gateway registration state.
        # CommandRouter checks the runtime flag, not just the GUI/state-store inventory.
        for device in self.device_registry.get_gui_device_presentations():
            device_id = str(device.get("id") or "")
            if not device_id:
                continue
            runtime = self.device_registry.get_runtime(device_id)
            runtime.live_registered = connected and (not reconnecting) and (device_id in registered_set)

        if connected and not reconnecting:
            self._attach_gateway_bus_proxies(registered_ids)
        else:
            self._detach_all_gateway_bus_proxies()

        self.state_store.set_bus_connection_state(
            connected=connected,
            reconnecting=reconnecting,
            wall_time=wall_time,
            sender=sender,
            bitrate=bitrate,
            registered_ids=registered_ids,
            skipped_ids=skipped_ids,
        )
        self.state_store.set_device_inventory(
            devices=self._build_device_inventory_with_live_registration(registered_ids),
            load_errors=self.device_registry.get_load_errors(),
        )

        if record_health:
            if reconnecting:
                event_name = "gateway_bus_reconnecting"
                severity = "warning"
            elif connected:
                event_name = "live_hardware_initialized_via_gateway"
                severity = "info"
            else:
                event_name = "live_hardware_shutdown_via_gateway"
                severity = "info"

            self.health.record_system_event(
                event_name,
                severity=severity,
                status=status,
                sender=sender,
                bitrate=bitrate,
                registered_ids=list(registered_ids),
                skipped_ids=list(skipped_ids),
                registered_count=len(registered_ids),
                skipped_count=len(skipped_ids),
            )

        self.health_monitor.sample_once()
        return {
            "connected": connected,
            "reconnecting": reconnecting,
            "status": status,
            "sender": sender,
            "bitrate": bitrate,
            "registered_ids": list(registered_ids),
            "skipped_ids": list(skipped_ids),
        }

    def _initialize_live_hardware_via_gateway(self) -> dict[str, Any]:
        responses = self.gateway_client.initialize_live_hardware()
        if not responses:
            raise RuntimeError(
                "Gateway did not acknowledge initialize_live_hardware"
            )

        first = responses[0]
        if first.type == "error":
            message = str(
                first.payload.get("message") or
                "Gateway initialize_live_hardware failed"
            )
            raise RuntimeError(message)

        if first.type != "hardware_status":
            raise RuntimeError(
                f"Unexpected gateway response to initialize_live_hardware: {first.type}"
            )

        payload = self._apply_gateway_hardware_status(
            first.payload,
            record_health=True,
        )
        self._apply_live_startup_state()
        return payload

    def _shutdown_live_hardware_via_gateway(self) -> dict[str, Any]:
        responses = self.gateway_client.shutdown_live_hardware()
        if not responses:
            raise RuntimeError(
                "Gateway did not acknowledge shutdown_live_hardware"
            )

        first = responses[0]
        if first.type == "error":
            message = str(
                first.payload.get("message") or
                "Gateway shutdown_live_hardware failed"
            )
            raise RuntimeError(message)

        if first.type != "hardware_status":
            raise RuntimeError(
                f"Unexpected gateway response to shutdown_live_hardware: {first.type}"
            )

        payload = self._apply_gateway_hardware_status(
            first.payload,
            record_health=True,
        )
        return payload

    def _initialize_live_hardware_locally(self) -> dict[str, Any]:
        result = self.bus_manager.initialize_live_hardware(self.device_registry)

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

        if result.already_running:
            self.health.record_system_event(
                "live_hardware_already_initialized",
                severity="info",
                message="Live hardware was already running; returning current state",
                sender=result.sender,
                bitrate=result.bitrate,
            )
        else:
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
        self._apply_live_startup_state()

        return {
            "connected": True,
            "sender": result.sender,
            "bitrate": result.bitrate,
            "registered_ids": list(result.registered_ids),
            "skipped_ids": list(result.skipped_ids),
        }

    def _shutdown_live_hardware_locally(self) -> dict[str, Any]:
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

        return {
            "connected": False,
            "sender": self.bus_manager.sender,
            "bitrate": self.bus_manager.bitrate,
            "registered_ids": [],
            "skipped_ids": [],
        }

    def _start_gateway_raw_run(
        self,
        *,
        run_result: Mapping[str, Any],
        original_payload: Mapping[str, Any],
    ) -> None:
        if not self.use_gateway_for_live_ingest:
            return

        responses = self.gateway_client.start_run(
            run_id=str(run_result["run_id"]),
            test_name=str(run_result["test_name"]),
            mode=str(run_result.get("mode") or "live"),
            operator=run_result.get("operator"),
            profile_name=run_result.get("profile_name"),
            notes=original_payload.get("notes"),
            software_git_commit=original_payload.get("software_git_commit"),
            software_branch=original_payload.get("software_branch"),
            device_map_version=original_payload.get("device_map_version"),
            svg_version=original_payload.get("svg_version"),
            bus_config=dict(original_payload.get("bus_config") or {}),
            clock_info=dict(original_payload.get("clock_info") or {}),
            extra_metadata=dict(original_payload.get("extra_metadata") or {}),
        )

        if not responses:
            raise RuntimeError("Gateway did not acknowledge start_run")

        first = responses[0]
        if first.type == "error":
            message = str(first.payload.get("message") or "Gateway start_run failed")
            raise RuntimeError(message)

        if first.type != "run_started":
            raise RuntimeError(
                f"Unexpected gateway response to start_run: {first.type}"
            )

        self._clear_orphaned_gateway_raw_run()

    def _finish_gateway_raw_run(
        self,
        *,
        run_id: str,
        reason: str,
    ) -> None:
        if not self.use_gateway_for_live_ingest:
            return

        responses = self.gateway_client.finish_run(
            run_id=run_id,
            reason=reason,
        )
        if not responses:
            raise RuntimeError(
                f"Gateway did not acknowledge finish_run for {run_id}"
            )

        first = responses[0]
        if first.type == "error":
            message = str(first.payload.get("message") or "Gateway finish_run failed")
            raise RuntimeError(message)

        if first.type != "run_finished":
            raise RuntimeError(
                f"Unexpected gateway response to finish_run: {first.type}"
            )

    def _set_orphaned_gateway_raw_run(
        self,
        payload: Mapping[str, Any],
    ) -> None:
        self._orphaned_gateway_raw_run = {
            "raw_run_id": self._get_optional_string(payload, "raw_run_id"),
            "raw_mode": self._get_optional_string(payload, "raw_mode"),
            "raw_test_name": self._get_optional_string(payload, "raw_test_name"),
            "raw_started_wall_time": self._get_optional_string(
                payload,
                "raw_started_wall_time",
            ),
            "backend_link_ok": payload.get("backend_link_ok"),
        }

    def _clear_orphaned_gateway_raw_run(self) -> None:
        self._orphaned_gateway_raw_run = None

    def _finish_orphaned_gateway_raw_run(
        self,
        *,
        reason: str,
    ) -> dict[str, Any]:
        orphaned = self._orphaned_gateway_raw_run
        if orphaned is None:
            raise RuntimeError("No orphaned gateway raw run is tracked")

        run_id = str(orphaned.get("raw_run_id") or "").strip()
        if not run_id:
            raise RuntimeError("Tracked orphaned gateway raw run is missing run_id")

        responses = self.gateway_client.finish_run(
            run_id=run_id,
            reason=reason,
        )
        if not responses:
            raise RuntimeError(
                f"Gateway did not acknowledge finish_run for orphaned raw run {run_id}"
            )

        first = responses[0]
        if first.type == "error":
            message = str(first.payload.get("message") or "Gateway finish_run failed")
            raise RuntimeError(message)

        if first.type != "run_finished":
            raise RuntimeError(
                f"Unexpected gateway response to finish_run: {first.type}"
            )

        self.health.record_system_event(
            "gateway_orphaned_raw_run_finished",
            severity="warning",
            run_id=run_id,
            mode=orphaned.get("raw_mode"),
            test_name=orphaned.get("raw_test_name"),
            reason=reason,
            raw_started_wall_time=orphaned.get("raw_started_wall_time"),
        )
        self._clear_orphaned_gateway_raw_run()
        self.health_monitor.sample_once()

        return {
            "run_id": run_id,
            "mode": orphaned.get("raw_mode") or "live",
            "status": "completed",
            "test_name": orphaned.get("raw_test_name"),
            "reason": reason,
            "finished_wall_time": isoformat_z(),
        }

    def adopt_gateway_runtime_status(self) -> dict[str, Any] | None:
        if not self.use_gateway_for_live_ingest:
            return None

        responses = self.gateway_client.status_request()
        if not responses:
            return None

        first = responses[0]
        if first.type == "error":
            log.warning(
                "Gateway status_request returned error: %s",
                first.payload.get("message"),
            )
            return None

        if first.type != "gateway_status":
            log.warning(
                "Unexpected gateway response to status_request: %s",
                first.type,
            )
            return None

        payload = self._normalize_mapping_payload(first.payload)

        adopted_bus_state = self._apply_gateway_hardware_status(
            {
                "connected": bool(payload.get("bus_connected", False)),
                "reconnecting": False,
                "status": "connected"
                if bool(payload.get("bus_connected", False))
                else "disconnected",
                "sender": self._get_optional_string(payload, "sender"),
                "bitrate": self._get_optional_int(payload, "bitrate"),
                "registered_ids": list(payload.get("registered_ids") or []),
                "skipped_ids": list(payload.get("skipped_ids") or []),
                "wall_time": isoformat_z(),
            },
            record_health=False,
        )

        raw_run_active = bool(payload.get("raw_run_active", False))
        if raw_run_active and not self.history_manager.is_running:
            self._set_orphaned_gateway_raw_run(payload)
        else:
            self._clear_orphaned_gateway_raw_run()

        self.health.record_system_event(
            "gateway_runtime_adopted",
            severity="warning" if raw_run_active else "info",
            gateway_bus_connected=adopted_bus_state["connected"],
            raw_run_active=raw_run_active,
            raw_run_id=self._get_optional_string(payload, "raw_run_id"),
            raw_mode=self._get_optional_string(payload, "raw_mode"),
            raw_test_name=self._get_optional_string(payload, "raw_test_name"),
            raw_started_wall_time=self._get_optional_string(
                payload,
                "raw_started_wall_time",
            ),
            backend_link_ok=payload.get("backend_link_ok"),
        )
        self.health_monitor.sample_once()
        return dict(payload)

    def _mirror_raw_event_to_gateway(
        self,
        stream_name: str,
        event: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if not self.use_gateway_for_live_ingest:
            return None
        if not self.history_manager.is_running:
            return None

        responses = self.gateway_client.record_raw_event(
            stream_name=stream_name,
            event=dict(event),
        )
        if not responses:
            log.warning(
                "Gateway did not acknowledge raw %s event mirror",
                stream_name,
            )
            return None

        first = responses[0]
        if first.type == "error":
            log.warning(
                "Gateway rejected raw %s event mirror: %s",
                stream_name,
                first.payload.get("message"),
            )
            return None

        mirrored_event = first.payload.get("event")
        if isinstance(mirrored_event, Mapping):
            return dict(mirrored_event)

        return None

    def _mirror_operator_action_to_gateway_if_running(
        self,
        action_event: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        return self._mirror_raw_event_to_gateway("operator_action", action_event)

    def _all_device_ids(self) -> list[str]:
        device_ids: list[str] = []
        for device in self.device_registry.get_gui_device_presentations():
            device_id = str(device.get("id") or "").strip()
            if device_id:
                device_ids.append(device_id)
        return device_ids

    def _detach_all_gateway_bus_proxies(self) -> None:
        for device_id in self._all_device_ids():
            if device_id not in self.device_registry:
                continue
            runtime = self.device_registry.get_runtime(device_id)
            current_bus = getattr(runtime, "_bus", None)
            proxy = self._gateway_bus_proxies_by_id.get(device_id)
            if proxy is not None and current_bus is proxy:
                runtime._bus = None
            if hasattr(runtime, "live_registered"):
                runtime.live_registered = False

        self._gateway_bus_proxies_by_id.clear()

    def _attach_gateway_bus_proxies(self, registered_ids: Iterable[str]) -> None:
        registered = {str(device_id) for device_id in registered_ids}
        log.info("[backend] _attach_gateway_bus_proxies registered_ids=%s", sorted(registered))

        self._detach_all_gateway_bus_proxies()

        for device_id in registered:
            if device_id not in self.device_registry:
                continue

            runtime = self.device_registry.get_runtime(device_id)
            proxy = GatewayBusProxy(
                gateway_client=self.gateway_client,
                device_id=device_id,
            )

            runtime._bus = proxy
            if hasattr(runtime, "live_registered"):
                runtime.live_registered = True

            self._gateway_bus_proxies_by_id[device_id] = proxy


    def _dispatch_command_request(
        self,
        payload: Mapping[str, Any],
        *,
        default_request_source: str,
    ) -> dict[str, Any]:
        normalized = self._normalize_mapping_payload(payload)
        normalized.setdefault("request_source", default_request_source)

        if default_request_source == "script":
            normalized.setdefault("authority_level", "script")
        else:
            normalized.setdefault("authority_level", "operator")

        action_payload = self._get_optional_mapping(normalized, "operator_action")
        if action_payload is not None:
            action_event = self._build_operator_action_event(action_payload)

            mirrored_action_event = self._mirror_operator_action_to_gateway_if_running(
                action_event
            )
            if mirrored_action_event is not None:
                action_event = mirrored_action_event

            self._record_operator_action_if_running(action_event)

        request_id = self._get_optional_string(normalized, "request_id")
        request_source = self._get_optional_string(normalized, "request_source") or default_request_source
        authority_level = self._get_optional_string(normalized, "authority_level") or (
            "script" if request_source == "script" else "operator"
        )
        command_name = self._require_non_empty_string(normalized, "command_name")
        device_id = self._get_optional_string(normalized, "device_id")

        self.health.record_system_event(
            "command_requested",
            severity="info",
            request_id=request_id,
            request_source=request_source,
            authority_level=authority_level,
            command_name=command_name,
            device_id=device_id,
        )

        dispatch_result = self.command_router.route_command(normalized)

        if dispatch_result.success and dispatch_result.command_event is not None:
            self._record_command_out_if_running(
                dispatch_result.command_event,
                result_summary=dispatch_result.result_summary,
            )
            self.health.record_system_event(
                "command_dispatched",
                severity="info",
                request_id=dispatch_result.request_id,
                request_source=dispatch_result.request_source,
                authority_level=dispatch_result.authority_level,
                command_name=dispatch_result.command_name,
                device_id=dispatch_result.device_id,
                adapter_name=dispatch_result.adapter_name,
                dispatched_via=dispatch_result.dispatched_via,
                run_mode=dispatch_result.run_mode,
            )
        elif dispatch_result.status == "rejected":
            self.health.record_system_event(
                "command_rejected",
                severity="warning",
                request_id=dispatch_result.request_id,
                request_source=dispatch_result.request_source,
                authority_level=dispatch_result.authority_level,
                command_name=dispatch_result.command_name,
                device_id=dispatch_result.device_id,
                adapter_name=dispatch_result.adapter_name,
                rejection_reason=dispatch_result.rejection_reason,
                interlock_reason=dispatch_result.interlock_reason,
                validation_errors=list(dispatch_result.validation_errors),
                state_reasons=list(dispatch_result.state_reasons),
                run_mode=dispatch_result.run_mode,
            )
        elif dispatch_result.status == "failed":
            self.health.record_system_event(
                "command_dispatch_failed",
                severity="error",
                request_id=dispatch_result.request_id,
                request_source=dispatch_result.request_source,
                authority_level=dispatch_result.authority_level,
                command_name=dispatch_result.command_name,
                device_id=dispatch_result.device_id,
                adapter_name=dispatch_result.adapter_name,
                message=dispatch_result.error,
                run_mode=dispatch_result.run_mode,
            )

        result_summary_mapping = dispatch_result.result_summary if isinstance(dispatch_result.result_summary, Mapping) else None
        self.state_store.mark_command_result(
            request_id=dispatch_result.request_id,
            requested_at=dispatch_result.requested_at,
            request_source=dispatch_result.request_source,
            authority_level=dispatch_result.authority_level,
            command_name=dispatch_result.command_name,
            device_id=dispatch_result.device_id,
            status=dispatch_result.status,
            dispatched_via=dispatch_result.dispatched_via,
            adapter_name=dispatch_result.adapter_name,
            run_mode=dispatch_result.run_mode,
            rejection_reason=dispatch_result.rejection_reason,
            interlock_reason=dispatch_result.interlock_reason,
            validation_errors=dispatch_result.validation_errors,
            state_reasons=dispatch_result.state_reasons,
            error=dispatch_result.error,
            result_summary=result_summary_mapping,
        )

        if dispatch_result.success:
            self._apply_optimistic_runtime_shadow_from_command(
                command_name=dispatch_result.command_name,
                device_id=dispatch_result.device_id,
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
            "state_reasons": list(dispatch_result.state_reasons),
            "error": dispatch_result.error,
            "request_id": dispatch_result.request_id,
            "request_source": dispatch_result.request_source,
            "authority_level": dispatch_result.authority_level,
            "run_mode": dispatch_result.run_mode,
            "requested_at": dispatch_result.requested_at,
        }

    def _apply_optimistic_runtime_shadow_from_command(
        self,
        *,
        command_name: str | None,
        device_id: str | None,
    ) -> None:
        if not isinstance(device_id, str) or not device_id:
            return

        normalized_command = str(command_name or "").strip().lower()
        if normalized_command in {"open", "open_valve", "valve_open"}:
            target_state = "open"
            target_value = True
        elif normalized_command in {"close", "close_valve", "valve_close"}:
            target_state = "closed"
            target_value = False
        else:
            return

        if device_id not in self.device_registry:
            return

        try:
            meta = self.device_registry.get_meta(device_id)
        except Exception:
            return

        if str(meta.get("deviceGroup") or "").upper() != "XV":
            return

        runtime = None
        try:
            runtime = self.device_registry.get_runtime(device_id)
        except Exception:
            runtime = None

        runtime_value = target_value
        runtime_aux = getattr(runtime, "aux", None) if runtime is not None else None
        runtime_time = getattr(runtime, "time", None) if runtime is not None else None
        live_registered = bool(getattr(runtime, "live_registered", False)) if runtime is not None else False

        if runtime is not None:
            raw_value = getattr(runtime, "value", None)
            if raw_value is not None:
                runtime_value = raw_value

        self.state_store.upsert_device_runtime_shadow(
            device_id=device_id,
            wall_time=isoformat_z(),
            source="command_out_optimistic",
            runtime_value=runtime_value,
            runtime_aux=runtime_aux,
            runtime_time=runtime_time,
            runtime_state=target_state,
            runtime_status=f"commanded_{target_state}",
            online=live_registered,
        )

    _VALID_STARTUP_STATES = frozenset({"open", "closed"})

    def _apply_live_startup_state(self) -> None:
        """Backend-process-lifetime bootstrap from settings.LIVE_STARTUP_STATE.

        Runs at most once per backend process.  For each XV in the config,
        seeds runtime state only if that device does not already have a
        stored ``runtime_state``.  Does NOT send hardware commands.  Later
        command-driven state updates overwrite seeded entries normally.
        """
        if self._live_startup_state_applied:
            return
        self._live_startup_state_applied = True

        startup_state = getattr(settings, "LIVE_STARTUP_STATE", None)
        if not startup_state:
            return

        valid_ids = set(settings.get_controllable_valve_ids())
        snapshot = self.state_store.get_snapshot()
        existing_by_id = snapshot.get("device_runtime", {}).get("by_id", {})
        wall_time = isoformat_z()
        applied = []

        for device_id, raw_value in startup_state.items():
            if device_id not in valid_ids:
                log.warning(
                    "LIVE_STARTUP_STATE: skipping %r - not an active controllable valve",
                    device_id,
                )
                continue

            state_value = str(raw_value).strip().lower()
            if state_value not in self._VALID_STARTUP_STATES:
                log.warning(
                    "LIVE_STARTUP_STATE: skipping %r for %r - expected 'open' or 'closed'",
                    raw_value,
                    device_id,
                )
                continue

            existing = existing_by_id.get(device_id, {})
            if existing.get("runtime_state") is not None:
                continue

            self.state_store.upsert_device_runtime_shadow(
                device_id=device_id,
                wall_time=wall_time,
                source="live_startup_seed",
                runtime_state=state_value,
            )
            applied.append(device_id)

        if applied:
            self.health.record_system_event(
                "live_startup_state_applied",
                severity="info",
                device_ids=applied,
                count=len(applied),
            )

    def _dispatch_script_command(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._dispatch_command_request(payload, default_request_source="script")

    def _dispatch_script_abort(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        from .abort_command import build_abort_dispatch_info, record_abort_system_event

        dispatch_info = build_abort_dispatch_info(payload, default_request_source="script")
        record_abort_system_event(
            self.health,
            dispatch_info,
            current_run_id=(
                self.history_manager.current_run.run_id
                if self.history_manager.current_run is not None
                else None
            ),
        )
        legacy_abort_message = dispatch_info.get("legacy_abort_message")
        if isinstance(legacy_abort_message, str):
            log.warning("%s", legacy_abort_message)
        self.health_monitor.sample_once()
        return dispatch_info

    def _reset_runtime_after_clear_abort_latch(self, dispatch_info: Mapping[str, Any]) -> None:
        if self.script_runner.is_running:
            log.warning("clear_abort_latch: stopping running script (reason=clear_abort_latch)")
            try:
                stop_result = self.script_runner.stop_script(reason="clear_abort_latch", timeout_s=1.0)
                self.state_store.mark_script_finished(
                    finished_wall_time=isoformat_z(),
                    return_code=stop_result.get("returncode"),
                    reason="clear_abort_latch",
                    exit_status="stopped",
                )
                self.state_store.clear_script_running_state()
            except Exception:
                log.exception("Failed to stop script runner while clearing abort latch")
        self.health.record_system_event(
            "script_runtime_reinitialized",
            severity="info",
            message="Abort latch cleared. Script/runtime state was reinitialized.",
            request_id=dispatch_info.get("request_id"),
            relay_request_id=dispatch_info.get("relay_request_id"),
            relay_session_id=dispatch_info.get("relay_session_id"),
            request_source=dispatch_info.get("request_source"),
            run_mode=dispatch_info.get("run_mode"),
        )
        self.health_monitor.sample_once()

    def _handle_script_output(self, info: Mapping[str, Any]) -> None:
        output_text = info.get("output_text")
        if not isinstance(output_text, str) or not output_text.strip():
            return
        self.state_store.append_script_output(output_text.strip())
        self.health.record_system_event(
            "script_output",
            severity="info",
            script_id=info.get("script_id"),
            name=info.get("name"),
            pid=info.get("pid"),
            launch_mode=info.get("launch_mode"),
            output_level=info.get("output_level"),
            message=output_text,
        )
        self.health_monitor.sample_once()

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
        failure_message = info.get("failure_message") if isinstance(info.get("failure_message"), str) else None

        if returncode == 0 and not failure_message:
            exit_status = "completed"
        elif failure_message or (isinstance(returncode, int) and returncode != 0):
            exit_status = "failed"
        else:
            exit_status = "exited"

        if failure_message:
            self.state_store.append_script_output(f"[error] {failure_message}")

        self.state_store.mark_script_finished(
            finished_wall_time=isoformat_z(),
            return_code=returncode if isinstance(returncode, int) else None,
            reason="process_exit",
            failure_message=failure_message,
            exit_status=exit_status,
        )
        self.state_store.clear_script_running_state()

        self.health.record_system_event(
            "script_exited",
            severity="info" if exit_status == "completed" else "warning",
            script_id=info.get("script_id"),
            name=info.get("name"),
            pid=info.get("pid"),
            launch_mode=info.get("launch_mode"),
            command=list(info.get("command", [])),
            cwd=info.get("cwd"),
            returncode=returncode,
            exit_status=exit_status,
            current_step_index=info.get("current_step_index"),
            total_steps=info.get("total_steps"),
            current_step_name=info.get("current_step_name"),
            current_step_type=info.get("current_step_type"),
            current_step_status=info.get("current_step_status"),
            failure_message=failure_message,
            is_held=info.get("is_held"),
            hold_requested=info.get("hold_requested"),
        )
        self.health_monitor.sample_once()

    def _process_telemetry_packet(
        self,
        *,
        meta: Mapping[str, Any],
        runtime: Any,
        packet: DataPacket,
        source: str,
        identity_override: Mapping[str, Any] | None = None,
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

        # If gateway already materialized the authoritative raw telemetry event
        # identity, apply it BEFORE using raw_event to build structured telemetry.
        if identity_override:
            raw_event = self._apply_raw_identity_to_structured_event(
                raw_event,
                identity_override,
            )

        # Backend is structured-only in gateway mode, so only write raw telemetry
        # locally if this HistoryManager actually has raw-side writers enabled.
        has_raw_side = bool(
            getattr(self.history_manager, "enable_raw_writer", False)
            or getattr(self.history_manager, "enable_rawbak_writer", False)
        )

        if self.history_manager.is_running and has_raw_side:
            raw_event_to_record = dict(raw_event)
            self.history_manager.record_raw_event("telemetry_in", raw_event_to_record)
            raw_event = raw_event_to_record

        reduction = self.reducer.apply_normalized_telemetry(
            telemetry=telemetry,
        )

        structured_event = self.structured_builder.build_structured_telemetry_event(
            telemetry=telemetry,
            reduction=reduction,
            first_order_event=raw_event,
        )

        # Critical: structured history must see the gateway identity BEFORE write.
        if identity_override:
            structured_event = self._apply_raw_identity_to_structured_event(
                structured_event,
                identity_override,
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
        if not self.history_manager.is_running:
            return

        structured_command_event = {
            **dict(command_event),
            "event_kind": "command_out",
            "structured_at": isoformat_z(),
            "result_summary": result_summary,
        }

        self.history_manager.record_structured_event(
            "command_out",
            structured_command_event,
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
            run_mode=status.get("run_mode"),
            connected_client_sessions=self.connected_client_sessions,
            health_summary=status.get("health_summary"),
            recording=status.get("recording"),
            mission_clock=status.get("mission_clock"),
            playback_clock=status.get("playback_clock"),
            last_command=status.get("last_command"),
        )

    def _register_client_hello(self, connection_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_client_session(connection_id, payload)

        with self._lock:
            previous = self._client_sessions_by_connection_id.get(connection_id)
            if previous is not None:
                normalized["connected_at"] = previous.get("connected_at") or normalized["connected_at"]
            self._client_sessions_by_connection_id[connection_id] = dict(normalized)

        self.state_store.upsert_gui_client_session(normalized)
        self.state_store.set_connected_clients(self.connected_client_count)
        self.health_monitor.sample_once()
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

    def _touch_client_session(self, client_id: str, message_type: str, *, is_ping: bool = False) -> None:
        self.state_store.touch_gui_client_session(
            connection_id=client_id,
            wall_time=isoformat_z(),
            message_type=message_type,
            is_ping=is_ping,
        )


    def _build_ingest_packet(
        self,
        normalized: Mapping[str, Any],
        *,
        meta: Mapping[str, Any],
    ) -> DataPacket:
        """Build a DataPacket from an IPC telemetry ingest payload."""
        seq = self._get_optional_int(normalized, "seq") or 1
        cmd = self._get_optional_int(normalized, "cmd") or 1
        reply = self._get_optional_bool(normalized, "reply", default=True)
        err = self._get_optional_bool(normalized, "err", default=False)
        rsvd = self._get_optional_bool(normalized, "rsvd", default=False)
        data = self._get_optional_int_list(normalized, "data") or [0, 0, 0, 0, 0, 0]

        packet = DataPacket(
            id=meta["address"],
            seq=seq,
            cmd=cmd,
            data=data,
            reply=reply,
            err=err,
            rsvd=rsvd,
        )

        packet_timestamp = normalized.get("packet_timestamp")
        if isinstance(packet_timestamp, (int, float)):
            packet.timestamp = float(packet_timestamp)

        return packet


    def _extract_raw_identity_fields(
        self,
        raw_event: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(raw_event, Mapping):
            return {}

        identity: dict[str, Any] = {}
        for key in (
            "run_id",
            "recorded_at",
            "stream",
            "stream_seq",
            "event_uid",
            "canonical_hash",
        ):
            if key in raw_event:
                identity[key] = raw_event[key]
        return identity


    def _apply_raw_identity_to_structured_event(
        self,
        structured_event: Mapping[str, Any],
        raw_identity: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not raw_identity:
            return dict(structured_event)

        merged = dict(structured_event)
        for key, value in raw_identity.items():
            merged[key] = value
        return merged

    def _ingest_mock_telemetry(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Ingest a mock/test telemetry packet through the real processing pipeline."""
        normalized = self._normalize_mapping_payload(payload)
        device_id = self._require_non_empty_string(normalized, "device_id")

        if device_id not in self.device_registry:
            raise ValueError(f"Unknown device_id: {device_id}")

        meta = self.device_registry.get_meta(device_id)
        runtime = self.device_registry.get_runtime(device_id)
        runtime_shadow = self._build_mock_runtime_shadow(
            runtime=runtime,
            payload=normalized,
        )

        packet = self._build_ingest_packet(normalized, meta=meta)

        return self._process_telemetry_packet(
            meta=meta,
            runtime=runtime_shadow,
            packet=packet,
            source="mock_ipc",
        )

    def _ingest_live_telemetry(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Ingest a live telemetry packet forwarded from the gateway."""
        normalized = self._normalize_mapping_payload(payload)
        device_id = self._require_non_empty_string(normalized, "device_id")

        if device_id not in self.device_registry:
            raise ValueError(f"Unknown device_id: {device_id}")

        meta = self.device_registry.get_meta(device_id)
        runtime = self.device_registry.get_runtime(device_id)

        raw_event = normalized.get("raw_event")
        raw_identity = self._extract_raw_identity_fields(raw_event)

        packet = self._build_ingest_packet(normalized, meta=meta)

        return self._process_telemetry_packet(
            meta=meta,
            runtime=runtime,
            packet=packet,
            source="gateway_live_bus",
            identity_override=raw_identity,
        )

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
