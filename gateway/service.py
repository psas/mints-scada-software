from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from historymanager import HistoryManager
from nexus import DataPacket

from backend.bus_manager import BusManager
from backend.device_registry import DeviceRegistry

from .backend_client import BackendIPCClient
from .ipc_models import (
    GatewayIPCMessage,
    error_message,
    gateway_status_message,
    hardware_status_message,
    hello_ack_message,
    packet_sent_message,
    pong_message,
    run_finished_message,
    run_started_message,
    raw_event_recorded_message,
)
from .ipc_server import GatewayIPCServer
from .models import GatewayRuntimeConfig

log = logging.getLogger(__name__)


def isoformat_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class GatewayService:
    """Gateway-owned live ingest service.

    This commit moves inbound live bus initialization and packet ingest into
    gateway, while backend still owns higher-level state, structured history,
    and GUI IPC.

    Outbound command routing is now also proxied through gateway.
    """

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        socket_path: Path | None = None,
        backend_socket_path: Path | None = None,
        idle_sleep_s: float = 0.25,
    ) -> None:
        if project_root is None:
            project_root = Path(__file__).resolve().parents[1]
        else:
            project_root = Path(project_root).expanduser().resolve()

        if socket_path is None:
            socket_path = project_root / ".gateway_service.sock"
        else:
            socket_path = Path(socket_path).expanduser().resolve()

        if backend_socket_path is None:
            backend_socket_path = project_root / ".backend_service.sock"
        else:
            backend_socket_path = Path(backend_socket_path).expanduser().resolve()

        self.config = GatewayRuntimeConfig(
            project_root=project_root,
            socket_path=socket_path,
            backend_socket_path=backend_socket_path,
            idle_sleep_s=idle_sleep_s,
        )

        self.service_name = "teststand-gateway"
        self.started_at = isoformat_z()
        self.supported_messages = [
            "hello",
            "ping",
            "status_request",
            "start_run",
            "finish_run",
            "record_raw_event",
            "initialize_live_hardware",
            "shutdown_live_hardware",
            "send_packet",
        ]

        self._lock = threading.RLock()
        self._connected_clients: set[str] = set()
        self._started = False
        self._last_registered_ids: list[str] = []
        self._last_skipped_ids: list[str] = []
        self._bus_connected = False
        self._backend_link_ok = True
        
        self.raw_history_manager = HistoryManager(
            project_root=project_root,
            enable_raw_writer=True,
            enable_rawbak_writer=True,
            enable_structured_writer=False,
        )

        self.backend_client = BackendIPCClient(
            project_root=project_root,
            socket_path=backend_socket_path,
        )

        self.device_registry = DeviceRegistry()
        self.device_registry.set_packet_listener(self._handle_device_packet)
        self.device_registry.load_from_settings()

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
            packet_callback=None,
            error_callback=self._handle_bus_error_event,
        )

        self.server = GatewayIPCServer(
            socket_path=self.socket_path,
            on_message=self.handle_message,
            on_client_connected=self.on_client_connected,
            on_client_disconnected=self.on_client_disconnected,
        )

    @property
    def project_root(self) -> Path:
        return self.config.project_root

    @property
    def socket_path(self) -> Path:
        return self.config.socket_path

    @property
    def backend_socket_path(self) -> Path:
        return self.config.backend_socket_path

    @property
    def connected_client_count(self) -> int:
        with self._lock:
            return len(self._connected_clients)

    @property
    def is_running(self) -> bool:
        return self._started

    def start(self) -> None:
        if self._started:
            log.debug("GatewayService.start() called while already started")
            return
        self._started = True
        log.info(
            "Gateway service started (project_root=%s, socket_path=%s, backend_socket=%s)",
            self.project_root,
            self.socket_path,
            self.backend_socket_path,
        )

    def serve_forever(self) -> None:
        if not self._started:
            self.start()

        log.info("Gateway service starting IPC server at %s", self.socket_path)
        try:
            self.server.serve_forever()
        finally:
            log.info("Gateway service IPC server exited")

    def stop(self) -> None:
        if not self._started:
            return

        log.info("Gateway service stopping")

        if self.raw_history_manager.is_running:
            try:
                self.raw_history_manager.finish_run(reason="gateway_shutdown")
            except Exception:
                log.exception("Gateway failed to finish raw/rawbak run during shutdown")

        try:
            self.backend_client.close()
        except Exception:
            log.exception("Gateway failed to close backend IPC client cleanly")

        try:
            self.bus_manager.shutdown_live_hardware()
        except Exception:
            log.exception("Gateway failed to shut down live hardware cleanly")

        self.device_registry.clear_live_registration_flags()
        self._bus_connected = False
        self._last_registered_ids = []
        self._last_skipped_ids = []
        self.server.stop()
        self._started = False

    def on_client_connected(self, client_id: str) -> None:
        with self._lock:
            self._connected_clients.add(client_id)
        log.info("Gateway IPC client connected: %s", client_id)

    def on_client_disconnected(self, client_id: str) -> None:
        with self._lock:
            self._connected_clients.discard(client_id)
        log.info("Gateway IPC client disconnected: %s", client_id)



    def _current_raw_run_summary(self) -> dict[str, Any]:
        current_run = self.raw_history_manager.current_run
        if current_run is None:
            return {
                "raw_run_active": False,
                "raw_run_id": None,
                "raw_mode": None,
                "raw_test_name": None,
                "raw_started_wall_time": None,
            }

        metadata = dict(current_run.metadata)
        return {
            "raw_run_active": True,
            "raw_run_id": current_run.run_id,
            "raw_mode": metadata.get("mode"),
            "raw_test_name": metadata.get("test_name"),
            "raw_started_wall_time": current_run.started_wall_time,
        }

    def _mark_backend_link_failure(self, reason: str) -> None:
        if self._backend_link_ok:
            log.warning("Gateway lost backend link: %s", reason)
        self._backend_link_ok = False

    def _mark_backend_link_restored(self) -> None:
        if not self._backend_link_ok:
            log.info("Gateway backend link restored")
        self._backend_link_ok = True


    def _build_status_message(self) -> GatewayIPCMessage:
        raw_run = self._current_raw_run_summary()
        return gateway_status_message(
            service_name=self.service_name,
            gateway_started_at=self.started_at,
            socket_path=str(self.socket_path),
            connected_clients=self.connected_client_count,
            supported_messages=self.supported_messages,
            bus_connected=self._bus_connected,
            sender=self.bus_manager.sender,
            bitrate=self.bus_manager.bitrate,
            registered_ids=self._last_registered_ids,
            skipped_ids=self._last_skipped_ids,
            raw_run_active=bool(raw_run["raw_run_active"]),
            raw_run_id=raw_run["raw_run_id"],
            raw_mode=raw_run["raw_mode"],
            raw_test_name=raw_run["raw_test_name"],
            raw_started_wall_time=raw_run["raw_started_wall_time"],
            backend_link_ok=self._backend_link_ok,
        )

    def _sync_hardware_status_to_backend(self, payload: Mapping[str, Any]) -> None:
        try:
            responses = self.backend_client.gateway_hardware_status(payload)
            if responses:
                self._mark_backend_link_restored()
            else:
                self._mark_backend_link_failure("hardware status sync returned no response")
        except Exception as exc:
            self._mark_backend_link_failure(f"hardware status sync failed: {exc}")

    def _handle_bus_status_event(self, payload: Mapping[str, Any]) -> None:
        status = str(payload.get("status") or "").strip().lower()
        connected = status in {"connected", "receive_loop_started"} or bool(payload.get("connected", False))
        reconnecting = status == "reconnecting" or bool(payload.get("reconnecting", False))

        registered_ids = list(payload.get("registered_ids") or self._last_registered_ids)
        skipped_ids = list(payload.get("skipped_ids") or self._last_skipped_ids)

        if connected:
            self._bus_connected = True
        elif status in {"disconnected", "receive_loop_stopped"}:
            self._bus_connected = False

        self._last_registered_ids = [str(x) for x in registered_ids]
        self._last_skipped_ids = [str(x) for x in skipped_ids]

        backend_payload = {
            "status": status,
            "reason": payload.get("reason"),
            "connected": self._bus_connected,
            "reconnecting": reconnecting,
            "sender": payload.get("sender", self.bus_manager.sender),
            "bitrate": payload.get("bitrate", self.bus_manager.bitrate),
            "registered_ids": list(self._last_registered_ids),
            "skipped_ids": list(self._last_skipped_ids),
            "registered_count": int(payload.get("registered_count", len(self._last_registered_ids))),
            "skipped_count": int(payload.get("skipped_count", len(self._last_skipped_ids))),
            "packet_listener_attached": payload.get("packet_listener_attached"),
            "wall_time": isoformat_z(),
        }
        self._sync_hardware_status_to_backend(backend_payload)

    def _handle_bus_error_event(self, payload: Mapping[str, Any]) -> None:
        log.warning("Gateway bus error event: %s", dict(payload))



    def _record_raw_telemetry_if_running(
        self,
        meta: Mapping[str, Any],
        packet: Any,
    ) -> dict[str, Any] | None:
        if not self.raw_history_manager.is_running:
            return None

        event = {
            "device_id": str(meta.get("id") or ""),
            "packet_id": int(getattr(packet, "id", meta.get("address", 0))),
            "seq": int(getattr(packet, "seq", 1)),
            "cmd": int(getattr(packet, "cmd", 1)),
            "reply": bool(getattr(packet, "reply", True)),
            "err": bool(getattr(packet, "err", False)),
            "rsvd": bool(getattr(packet, "rsvd", False)),
            "data": [
                int(x)
                for x in list(getattr(packet, "data", [0, 0, 0, 0, 0, 0]) or [])
            ],
            "packet_timestamp": getattr(packet, "timestamp", None),
            "source": "gateway_live_bus",
        }
        self.raw_history_manager.record_raw_event("telemetry_in", event)
        return dict(event)

    def _record_raw_command_out_if_running(
        self,
        *,
        device_id: str | None,
        packet: DataPacket,
    ) -> None:
        if not self.raw_history_manager.is_running:
            return

        event = {
            "device_id": device_id,
            "packet_id": int(getattr(packet, "id")),
            "seq": int(getattr(packet, "seq", 1)),
            "cmd": int(getattr(packet, "cmd", 1)),
            "reply": bool(getattr(packet, "reply", False)),
            "err": bool(getattr(packet, "err", False)),
            "rsvd": bool(getattr(packet, "rsvd", False)),
            "data": [int(x) for x in list(getattr(packet, "data", []) or [])],
            "sender": self.bus_manager.sender,
            "bitrate": self.bus_manager.bitrate,
            "source": "gateway_send_packet",
        }
        self.raw_history_manager.record_raw_event("command_out", event)

    def _record_external_raw_event_if_running(
        self,
        *,
        stream_name: str,
        event: Mapping[str, Any],
    ) -> tuple[str | None, dict[str, Any] | None]:
        if not self.raw_history_manager.is_running:
            return None, None

        event_payload = dict(event)
        self.raw_history_manager.record_raw_event(stream_name, event_payload)

        current_run = self.raw_history_manager.current_run
        run_id = current_run.run_id if current_run is not None else None
        return run_id, event_payload

    def _handle_device_packet(self, meta: dict[str, Any], runtime: Any, packet: Any) -> None:
        del runtime

        materialized_raw_event: dict[str, Any] | None = None

        try:
            materialized_raw_event = self._record_raw_telemetry_if_running(meta, packet)
        except Exception:
            log.exception("Gateway failed to record raw telemetry_in for %s", meta.get("id"))

        try:
            responses = self.backend_client.ingest_live_packet(
                meta=meta,
                packet=packet,
                raw_event=materialized_raw_event,
            )
            if responses:
                self._mark_backend_link_restored()
            else:
                self._mark_backend_link_failure("live packet forward returned no response")
        except Exception as exc:
            self._mark_backend_link_failure(
                f"live packet forward failed for {meta.get('id')}: {exc}"
            )

    def _build_outbound_packet(self, payload: Mapping[str, Any]) -> DataPacket:
        packet_id = int(payload["id"])
        seq = int(payload.get("seq", 1))
        cmd = int(payload.get("cmd", 1))
        reply = bool(payload.get("reply", False))
        err = bool(payload.get("err", False))
        rsvd = bool(payload.get("rsvd", False))

        data = [int(x) & 0xFF for x in list(payload.get("data") or [])]
        if len(data) > 6:
            raise ValueError("Outbound packet payload 'data' cannot exceed 6 bytes")
        while len(data) < 6:
            data.append(0)

        return DataPacket(
            id=packet_id,
            seq=seq,
            cmd=cmd,
            reply=reply,
            err=err,
            rsvd=rsvd,
            data=data,
        )

    def _resolve_live_bus_for_device(self, device_id: str | None):
        if device_id and device_id in self.device_registry:
            runtime = self.device_registry.get_runtime(device_id)
            bus = getattr(runtime, "_bus", None)
            if bus is not None:
                return bus

        for registered_id in self._last_registered_ids:
            if registered_id not in self.device_registry:
                continue
            runtime = self.device_registry.get_runtime(registered_id)
            bus = getattr(runtime, "_bus", None)
            if bus is not None:
                return bus

        return None

    def handle_message(
        self,
        client_id: str,
        message: GatewayIPCMessage,
    ) -> Iterable[GatewayIPCMessage]:
        if message.type == "hello":
            yield hello_ack_message(
                service_name=self.service_name,
                gateway_started_at=self.started_at,
                connected_clients=self.connected_client_count,
                supported_messages=self.supported_messages,
            )
            yield self._build_status_message()
            return

        if message.type == "ping":
            yield pong_message()
            return

        if message.type == "status_request":
            yield self._build_status_message()
            return


        if message.type == "record_raw_event":
            try:
                payload = dict(message.payload)
                stream_name = str(payload["stream_name"])
                event_payload = payload.get("event")
                if not isinstance(event_payload, Mapping):
                    raise ValueError("record_raw_event requires 'event' to be a mapping")

                run_id, materialized_event = self._record_external_raw_event_if_running(
                    stream_name=stream_name,
                    event=event_payload,
                )
                if run_id is None or materialized_event is None:
                    yield error_message(
                        code="gateway_raw_run_not_active",
                        message="Gateway raw/rawbak run is not active",
                    )
                    return

                yield raw_event_recorded_message(
                    stream_name=stream_name,
                    run_id=run_id,
                    accepted=True,
                    event=materialized_event,
                )
            except Exception as exc:
                yield error_message(
                    code="record_raw_event_failed",
                    message=str(exc),
                )
            return

        if message.type == "start_run":
            try:
                payload = dict(message.payload)

                run_id = self.raw_history_manager.start_run(
                    test_name=str(payload["test_name"]),
                    mode=str(payload.get("mode") or "live"),
                    run_id=str(payload["run_id"]),
                    operator=payload.get("operator"),
                    profile_name=payload.get("profile_name"),
                    notes=payload.get("notes"),
                    software_git_commit=payload.get("software_git_commit"),
                    software_branch=payload.get("software_branch"),
                    device_map_version=payload.get("device_map_version"),
                    svg_version=payload.get("svg_version"),
                    bus_config=dict(payload.get("bus_config") or {}),
                    clock_info=dict(payload.get("clock_info") or {}),
                    extra_metadata=dict(payload.get("extra_metadata") or {}),
                )

                current_run = self.raw_history_manager.current_run
                started_wall_time = (
                    current_run.started_wall_time if current_run is not None else isoformat_z()
                )

                yield run_started_message(
                    run_id=run_id,
                    mode=str(payload.get("mode") or "live"),
                    status="running",
                    test_name=str(payload["test_name"]),
                    operator=payload.get("operator"),
                    profile_name=payload.get("profile_name"),
                    started_wall_time=started_wall_time,
                )
            except Exception as exc:
                yield error_message(
                    code="gateway_start_run_failed",
                    message=str(exc),
                )
            return

        if message.type == "finish_run":
            try:
                payload = dict(message.payload)
                reason = str(payload.get("reason") or "operator_stop")

                current_run = self.raw_history_manager.current_run
                current_mode = None
                current_test_name = None
                if current_run is not None:
                    current_mode = current_run.metadata.get("mode")
                    current_test_name = current_run.metadata.get("test_name")

                finished_run_id = self.raw_history_manager.finish_run(reason=reason)

                yield run_finished_message(
                    run_id=finished_run_id,
                    mode=str(current_mode or "live"),
                    status="completed",
                    test_name=current_test_name,
                    reason=reason,
                    finished_wall_time=isoformat_z(),
                )
            except Exception as exc:
                yield error_message(
                    code="gateway_finish_run_failed",
                    message=str(exc),
                )
            return

        if message.type == "initialize_live_hardware":
            try:
                result = self.bus_manager.initialize_live_hardware(self.device_registry)
            except Exception as exc:
                yield error_message(
                    code="initialize_live_hardware_failed",
                    message=str(exc),
                )
                return

            self._bus_connected = True
            self._last_registered_ids = list(result.registered_ids)
            self._last_skipped_ids = list(result.skipped_ids)

            payload = hardware_status_message(
                connected=True,
                reconnecting=False,
                status="connected",
                reason="gateway_initialize_live_hardware",
                sender=result.sender,
                bitrate=result.bitrate,
                registered_ids=result.registered_ids,
                skipped_ids=result.skipped_ids,
                registered_count=result.registered_count,
                skipped_count=result.skipped_count,
                already_running=result.already_running,
                packet_listener_attached=True,
                wall_time=isoformat_z(),
            )
            self._sync_hardware_status_to_backend(payload.payload)
            yield payload
            return

        if message.type == "shutdown_live_hardware":
            try:
                self.bus_manager.shutdown_live_hardware()
            finally:
                self.device_registry.clear_live_registration_flags()

            self._bus_connected = False
            self._last_registered_ids = []
            self._last_skipped_ids = []

            payload = hardware_status_message(
                connected=False,
                reconnecting=False,
                status="disconnected",
                reason="gateway_shutdown_live_hardware",
                sender=self.bus_manager.sender,
                bitrate=self.bus_manager.bitrate,
                registered_ids=[],
                skipped_ids=[],
                registered_count=0,
                skipped_count=0,
                wall_time=isoformat_z(),
            )
            self._sync_hardware_status_to_backend(payload.payload)
            yield payload
            return

        if message.type == "send_packet":
            try:
                payload = dict(message.payload)
                device_id_raw = payload.get("device_id")
                device_id = str(device_id_raw) if device_id_raw is not None else None

                if not self._bus_connected:
                    raise RuntimeError("gateway live bus is not connected")

                bus = self._resolve_live_bus_for_device(device_id)
                if bus is None:
                    raise RuntimeError(
                        f"gateway has no live bus handle for device {device_id!r}"
                    )

                packet = self._build_outbound_packet(payload)
                bus.send(packet)

                self._record_raw_command_out_if_running(
                    device_id=device_id,
                    packet=packet,
                )

                yield packet_sent_message(
                    device_id=device_id,
                    packet_id=int(getattr(packet, "id")),
                    seq=int(getattr(packet, "seq", 1)),
                    cmd=int(getattr(packet, "cmd", 1)),
                    sender=self.bus_manager.sender,
                    bitrate=self.bus_manager.bitrate,
                )
            except Exception as exc:
                yield error_message(
                    code="send_packet_failed",
                    message=str(exc),
                )
            return

        yield error_message(
            code="unsupported_message",
            message=f"Unsupported gateway IPC message type: {message.type}",
            details={
                "client_id": client_id,
                "supported_messages": self.supported_messages,
            },
        )