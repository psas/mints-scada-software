from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Iterable, Mapping

from historymanager import HistoryManager
from historymanager.manager import isoformat_z
from nexus import DataPacket

from .bus_manager import BusManager
from .device_registry import DeviceRegistry
from .ipc_models import (
    IPCMessage,
    backend_status_message,
    device_inventory_message,
    error_message,
    hardware_status_message,
    hello_ack_message,
    pong_message,
    run_status_message,
    state_snapshot_message,
    structured_event_message,
)
from .ipc_server import IPCServer
from .reducer import Reducer
from .run_controller import RunController
from .state_store import StateStore
from .structured_builder import StructuredEventBuilder


class BackendService:
    """Backend service skeleton.

    Commit 7 adds:
    - reducer pipeline
    - structured event builder
    - packet hook from runtime devices into backend
    - generic telemetry persistence path
    - mock telemetry IPC for smoke testing without real hardware
    """

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
            devices=self.device_registry.get_device_summaries(),
            load_errors=self.device_registry.get_load_errors(),
        )

        self.bus_manager = BusManager()

        if socket_path is None:
            if self.project_root is None:
                socket_path = Path(".backend_service.sock").resolve()
            else:
                socket_path = self.project_root / ".backend_service.sock"

        self.socket_path = Path(socket_path).expanduser().resolve()

        self._lock = threading.RLock()
        self._connected_clients: set[str] = set()

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
            devices=self.device_registry.get_device_summaries(),
            load_errors=self.device_registry.get_load_errors(),
        )
        self.server.stop()

    def on_client_connected(self, client_id: str) -> None:
        with self._lock:
            self._connected_clients.add(client_id)
            self.state_store.set_connected_clients(len(self._connected_clients))

    def on_client_disconnected(self, client_id: str) -> None:
        with self._lock:
            self._connected_clients.discard(client_id)
            self.state_store.set_connected_clients(len(self._connected_clients))

    def handle_message(self, client_id: str, message: IPCMessage) -> Iterable[IPCMessage]:
        if message.type == "hello":
            yield hello_ack_message(
                service_name=self.service_name,
                backend_started_at=self.started_at,
                connected_clients=self.connected_client_count,
                supported_messages=self.supported_messages,
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
                devices=self.device_registry.get_device_summaries(),
                load_errors=self.device_registry.get_load_errors(),
            )

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
                devices=self.device_registry.get_device_summaries(),
                load_errors=self.device_registry.get_load_errors(),
            )

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
                finish_result = self.run_controller.finish_run(reason=reason)
            except Exception as exc:
                yield error_message("finish_run_failed", str(exc))
                return

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

                structured_event = self._process_telemetry_packet(
                    meta=meta,
                    runtime=runtime,
                    packet=packet,
                    source="mock_ipc",
                )
            except Exception as exc:
                yield error_message("ingest_mock_telemetry_failed", str(exc))
                return

            yield structured_event_message(structured_event)
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

    def _handle_device_packet(self, meta: dict[str, Any], runtime: Any, packet: Any) -> None:
        self._process_telemetry_packet(
            meta=meta,
            runtime=runtime,
            packet=packet,
            source="bus",
        )

    def _process_telemetry_packet(
        self,
        *,
        meta: dict[str, Any],
        runtime: Any,
        packet: Any,
        source: str,
    ) -> dict[str, Any]:
        raw_event = self.structured_builder.build_raw_telemetry_event(
            meta=meta,
            packet=packet,
            source=source,
        )

        if self.history_manager.is_running:
            self.history_manager.record_raw_event("telemetry_in", raw_event)

        reduction = self.reducer.apply_telemetry_packet(
            meta=meta,
            runtime=runtime,
            packet=packet,
            source=source,
        )

        structured_event = self.structured_builder.build_structured_telemetry_event(
            meta=meta,
            reduction=reduction,
        )

        if self.history_manager.is_running:
            self.history_manager.record_structured_event(
                "telemetry_in",
                structured_event,
            )

        return structured_event

    def _build_backend_status_message(self) -> IPCMessage:
        status = self.state_store.get_backend_status()
        return backend_status_message(
            backend_started_at=status["backend_started_at"],
            connected_clients=status["connected_clients"],
            active_run_id=status["active_run_id"],
            is_running=status["is_running"],
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