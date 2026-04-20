"""gateway/service.py

Gateway-owned live ingest service and IPC boundary.

This module hosts the gateway process that owns live hardware initialization,
packet ingest, raw/rawbak history recording, and gateway-side IPC handling. It
forwards higher-level state updates to the backend while keeping the backend as
the system of record for authoritative runtime state and structured history.
"""

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
    abort_result_message,
    clear_abort_latch_result_message,
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
from scripts.script_runtime.abort_flow_contract import (
    CLEAR_ABORT_LATCH_RELAY_MESSAGE_TYPE,
)
from scripts.script_runtime.script_contract import ABORT_RELAY_MESSAGE_TYPE

log = logging.getLogger(__name__)

ABORT_LATCHED_PLACEHOLDER_MESSAGE = "ABORT LATCHED !!! PRESS THE E-STOP BUTTON NOW !!!"
CLEAR_ABORT_LATCH_REINITIALIZED_MESSAGE = "Abort latch cleared. Returning to normal mode with fresh initialized runtime state."

ABORT_LATCHED_PLACEHOLDER_TODOS = (
    "TODO(psas-abort-fastpath): gateway abort is currently a placeholder only.",
    "TODO(psas-abort-fastpath): define the real hardware-side abort behavior here.",
    "TODO(psas-abort-fastpath): future options may include forwarding an abort packet, forcing safe state, or running a dedicated abort routine.",
)


def isoformat_z() -> str:
    """Return the current UTC time formatted as a whole-second Z timestamp.

    Returns:
        The current UTC timestamp in ISO 8601 format with a ``Z`` suffix and no
        fractional seconds.
    """
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class GatewayService:
    """Own gateway-side live hardware, raw history, and IPC responsibilities.

    The gateway process owns live bus initialization, inbound packet ingest,
    raw/rawbak recording, gateway IPC, and forwarding of live hardware status
    and relay-driven abort actions to the backend. The backend remains the
    system of record for authoritative runtime state and structured history.
    """

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        socket_path: Path | None = None,
        backend_socket_path: Path | None = None,
        idle_sleep_s: float = 0.25,
    ) -> None:
        """Initialize gateway runtime dependencies and IPC wiring.

        Args:
            project_root: Project root used for default socket and history
                locations. Defaults to the repository root.
            socket_path: Unix domain socket path exposed by the gateway IPC
                server. Defaults to ``.gateway_service.sock`` under the project
                root.
            backend_socket_path: Unix domain socket path for the backend IPC
                service. Defaults to ``.backend_service.sock`` under the
                project root.
            idle_sleep_s: Idle sleep interval for the runtime configuration.
        """
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
            ABORT_RELAY_MESSAGE_TYPE,
            CLEAR_ABORT_LATCH_RELAY_MESSAGE_TYPE,
        ]

        self._lock = threading.RLock()
        self._connected_clients: set[str] = set()
        self._started = False
        self._last_registered_ids: list[str] = []
        self._last_skipped_ids: list[str] = []
        self._bus_connected = False
        self._backend_link_ok = True
        self._last_backend_link_failure_reason: str | None = None
        self._abort_latched = False
        self._abort_latched_at: str | None = None
        self._abort_latched_request_id: str | None = None
        self._abort_latched_session_id: str | None = None

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
        """Return the resolved project root for the gateway runtime.

        Returns:
            The configured project root path.
        """
        return self.config.project_root

    @property
    def socket_path(self) -> Path:
        """Return the gateway IPC socket path.

        Returns:
            The Unix domain socket path served by the gateway.
        """
        return self.config.socket_path

    @property
    def backend_socket_path(self) -> Path:
        """Return the backend IPC socket path used by the gateway client.

        Returns:
            The Unix domain socket path for backend IPC.
        """
        return self.config.backend_socket_path

    @property
    def connected_client_count(self) -> int:
        """Return the current number of connected gateway IPC clients.

        Returns:
            The number of clients currently tracked by the gateway server.
        """
        with self._lock:
            return len(self._connected_clients)

    @property
    def is_running(self) -> bool:
        """Return whether the gateway service has been started.

        Returns:
            True when the gateway runtime has been started.
        """
        return self._started

    def start(self) -> None:
        """Mark the gateway service as started and log startup metadata."""
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
        """Start the gateway if needed and run the IPC server loop."""
        if not self._started:
            self.start()

        log.info("Gateway service starting IPC server at %s", self.socket_path)
        try:
            self.server.serve_forever()
        finally:
            log.info("Gateway service IPC server exited")

    def stop(self) -> None:
        """Stop gateway-owned runtime resources and clear live state.

        The shutdown path attempts to finish any active raw/rawbak run, close
        the backend IPC client, shut down live hardware, clear registration
        flags, and stop the gateway IPC server.
        """
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
        """Track a newly connected gateway IPC client.

        Args:
            client_id: Gateway server client identifier.
        """
        with self._lock:
            self._connected_clients.add(client_id)
        log.info("Gateway IPC client connected: %s", client_id)

    def on_client_disconnected(self, client_id: str) -> None:
        """Forget a disconnected gateway IPC client.

        Args:
            client_id: Gateway server client identifier.
        """
        with self._lock:
            self._connected_clients.discard(client_id)
        log.info("Gateway IPC client disconnected: %s", client_id)

    def _current_raw_run_summary(self) -> dict[str, Any]:
        """Build the current raw/rawbak run summary for status replies.

        Returns:
            A summary dictionary describing whether a raw run is active and, if
            so, its run identifier, mode, test name, and wall-clock start time.
        """
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
        """Mark the backend link unhealthy and retain the latest failure reason.

        Args:
            reason: Human-readable failure summary for logs and status state.
        """
        if self._backend_link_ok or self._last_backend_link_failure_reason != reason:
            log.warning("Gateway lost backend link: %s", reason)
        self._backend_link_ok = False
        self._last_backend_link_failure_reason = reason

    def _mark_backend_link_restored(self) -> None:
        """Mark the backend link healthy and clear the failure reason."""
        if not self._backend_link_ok:
            log.info("Gateway backend link restored")
        self._backend_link_ok = True
        self._last_backend_link_failure_reason = None

    def _build_status_message(self) -> GatewayIPCMessage:
        """Build the canonical gateway status reply.

        Returns:
            A gateway status IPC message containing service metadata, live bus
            state, raw run summary, backend-link health, and abort-latch state.
        """
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
            abort_latched=self._abort_latched,
            abort_latched_at=self._abort_latched_at,
            abort_relay_request_id=self._abort_latched_request_id,
        )

    def _latch_abort(self, payload: Mapping[str, Any]) -> None:
        """Latch gateway abort placeholder state for a relay abort request.

        The latch records the first abort timestamp and relay identifiers, then
        emits the placeholder abort log messages. Subsequent abort requests only
        refresh the stored relay identifiers when new values are present.

        Args:
            payload: Gateway abort relay payload.
        """
        relay_request_id = str(payload.get("relay_request_id") or "") or None
        relay_session_id = str(payload.get("relay_session_id") or "") or None
        if self._abort_latched:
            if relay_request_id is not None:
                self._abort_latched_request_id = relay_request_id
            if relay_session_id is not None:
                self._abort_latched_session_id = relay_session_id
            return

        self._abort_latched = True
        self._abort_latched_at = isoformat_z()
        self._abort_latched_request_id = relay_request_id
        self._abort_latched_session_id = relay_session_id

        log.critical(ABORT_LATCHED_PLACEHOLDER_MESSAGE)
        for line in ABORT_LATCHED_PLACEHOLDER_TODOS:
            log.critical(line)

    def _record_abort_placeholder_raw_event(self, payload: Mapping[str, Any]) -> None:
        """Record the placeholder gateway abort latch event into raw history.

        Args:
            payload: Gateway abort relay payload.
        """
        if not self.raw_history_manager.is_running:
            return
        event = {
            "event_type": "system_event",
            "event_name": "gateway_abort_latched",
            "severity": "critical",
            "message": ABORT_LATCHED_PLACEHOLDER_MESSAGE,
            "relay_request_id": payload.get("relay_request_id"),
            "relay_session_id": payload.get("relay_session_id"),
            "source_window_role": payload.get("source_window_role"),
            "source_window_kind": payload.get("source_window_kind"),
            "source_mode": payload.get("source_mode"),
            "requested_via": payload.get("requested_via"),
            "placeholder_todos": list(ABORT_LATCHED_PLACEHOLDER_TODOS),
            "wall_time": isoformat_z(),
        }
        self.raw_history_manager.record_raw_event("system_event", event)

    def _forward_abort_to_backend(
        self, payload: Mapping[str, Any]
    ) -> tuple[bool, str | None]:
        """Forward the relay-driven abort action and command payloads to backend.

        Args:
            payload: Gateway abort relay payload containing ``operator_action``
                and ``command_payload``.

        Returns:
            A tuple of ``(forwarded, reason)`` describing whether the backend
            accepted the forward and the backend-side failure reason when it did
            not.
        """
        operator_action_payload = dict(payload.get("operator_action") or {})
        command_payload = dict(payload.get("command_payload") or {})
        if not operator_action_payload or not command_payload:
            return (
                False,
                "gateway abort request requires operator_action and command_payload",
            )
        try:
            forwarded, reason = self.backend_client.forward_abort_to_backend(
                operator_action_payload=operator_action_payload,
                command_payload=command_payload,
            )
        except Exception as exc:
            self._mark_backend_link_failure(f"gateway abort forward failed: {exc}")
            return False, str(exc)

        if forwarded:
            self._mark_backend_link_restored()
        else:
            self._mark_backend_link_failure(
                reason or "gateway abort forward was rejected"
            )
        return forwarded, reason

    def _handle_abort_request_message(
        self, payload: Mapping[str, Any]
    ) -> GatewayIPCMessage:
        """Handle the gateway abort relay message end to end.

        This latches the gateway abort placeholder state, records the matching
        raw system event when raw recording is active, forwards the abort to the
        backend, and returns the gateway abort result message.

        Args:
            payload: Gateway abort relay payload.

        Returns:
            The gateway abort result IPC message.
        """
        self._latch_abort(payload)
        try:
            self._record_abort_placeholder_raw_event(payload)
        except Exception:
            log.exception("Gateway failed to record abort placeholder raw event")

        forwarded, backend_error = self._forward_abort_to_backend(payload)
        return abort_result_message(
            ok=True,
            abort_latched=self._abort_latched,
            relay_request_id=str(payload.get("relay_request_id") or "") or None,
            relay_session_id=str(payload.get("relay_session_id") or "") or None,
            backend_forwarded=forwarded,
            backend_error=backend_error,
            placeholder_message=ABORT_LATCHED_PLACEHOLDER_MESSAGE,
            wall_time=isoformat_z(),
        )

    def _clear_abort_latch(self, payload: Mapping[str, Any]) -> bool:
        """Clear the gateway abort latch and reset stored relay identifiers.

        Args:
            payload: Clear-abort relay payload. The payload is accepted for API
                symmetry but is not currently inspected by this method.

        Returns:
            True when the latch had previously been active.
        """
        was_latched = bool(self._abort_latched)
        self._abort_latched = False
        self._abort_latched_at = None
        self._abort_latched_request_id = None
        self._abort_latched_session_id = None

        if was_latched:
            log.warning(CLEAR_ABORT_LATCH_REINITIALIZED_MESSAGE)
        return was_latched

    def _record_clear_abort_latch_raw_event(
        self, payload: Mapping[str, Any], *, was_latched: bool
    ) -> None:
        """Record the clear-abort-latch gateway event into raw history.

        Args:
            payload: Clear-abort relay payload.
            was_latched: Whether the gateway abort latch had been active before
                clearing it.
        """
        if not self.raw_history_manager.is_running:
            return
        event = {
            "event_type": "system_event",
            "event_name": "gateway_abort_latch_cleared",
            "severity": "warning",
            "message": CLEAR_ABORT_LATCH_REINITIALIZED_MESSAGE,
            "relay_request_id": payload.get("relay_request_id"),
            "relay_session_id": payload.get("relay_session_id"),
            "source_window_role": payload.get("source_window_role"),
            "source_window_kind": payload.get("source_window_kind"),
            "source_mode": payload.get("source_mode"),
            "requested_via": payload.get("requested_via"),
            "was_latched": bool(was_latched),
            "wall_time": isoformat_z(),
        }
        self.raw_history_manager.record_raw_event("system_event", event)

    def _forward_clear_abort_latch_to_backend(
        self, payload: Mapping[str, Any]
    ) -> tuple[bool, str | None]:
        """Forward the clear-abort-latch action and command payloads to backend.

        Args:
            payload: Clear-abort relay payload containing ``operator_action`` and
                ``command_payload``.

        Returns:
            A tuple of ``(forwarded, reason)`` describing whether the backend
            accepted the forward and the backend-side failure reason when it did
            not.
        """
        operator_action_payload = dict(payload.get("operator_action") or {})
        command_payload = dict(payload.get("command_payload") or {})
        if not operator_action_payload or not command_payload:
            return (
                False,
                "clear abort latch request requires operator_action and command_payload",
            )
        try:
            forwarded, reason = (
                self.backend_client.forward_clear_abort_latch_to_backend(
                    operator_action_payload=operator_action_payload,
                    command_payload=command_payload,
                )
            )
        except Exception as exc:
            self._mark_backend_link_failure(f"clear abort latch forward failed: {exc}")
            return False, str(exc)

        if forwarded:
            self._mark_backend_link_restored()
        else:
            self._mark_backend_link_failure(
                reason or "clear abort latch forward was rejected"
            )
        return forwarded, reason

    def _handle_clear_abort_latch_request_message(
        self, payload: Mapping[str, Any]
    ) -> GatewayIPCMessage:
        """Handle the clear-abort-latch relay message end to end.

        Args:
            payload: Clear-abort relay payload.

        Returns:
            The gateway clear-abort-latch result IPC message.
        """
        was_latched = self._clear_abort_latch(payload)
        try:
            self._record_clear_abort_latch_raw_event(payload, was_latched=was_latched)
        except Exception:
            log.exception("Gateway failed to record clear abort latch raw event")

        forwarded, backend_error = self._forward_clear_abort_latch_to_backend(payload)
        return clear_abort_latch_result_message(
            ok=True,
            abort_latched=self._abort_latched,
            was_latched=was_latched,
            relay_request_id=str(payload.get("relay_request_id") or "") or None,
            relay_session_id=str(payload.get("relay_session_id") or "") or None,
            backend_forwarded=forwarded,
            backend_error=backend_error,
            message=CLEAR_ABORT_LATCH_REINITIALIZED_MESSAGE,
            wall_time=isoformat_z(),
        )

    def _sync_hardware_status_to_backend(self, payload: Mapping[str, Any]) -> None:
        """Forward gateway hardware status into the backend link-health path.

        Args:
            payload: Gateway hardware status payload sent to backend.
        """
        try:
            responses = self.backend_client.gateway_hardware_status(payload)
            if responses:
                self._mark_backend_link_restored()
            else:
                self._mark_backend_link_failure(
                    "hardware status sync returned no response"
                )
        except Exception as exc:
            self._mark_backend_link_failure(f"hardware status sync failed: {exc}")

    def _handle_bus_status_event(self, payload: Mapping[str, Any]) -> None:
        """Translate a BusManager status callback into backend hardware status.

        Args:
            payload: Bus-status callback payload emitted by ``BusManager``.
        """
        status = str(payload.get("status") or "").strip().lower()
        connected = status in {"connected", "receive_loop_started"} or bool(
            payload.get("connected", False)
        )
        reconnecting = status == "reconnecting" or bool(
            payload.get("reconnecting", False)
        )

        registered_ids = list(
            payload.get("registered_ids") or self._last_registered_ids
        )
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
            "registered_count": int(
                payload.get("registered_count", len(self._last_registered_ids))
            ),
            "skipped_count": int(
                payload.get("skipped_count", len(self._last_skipped_ids))
            ),
            "packet_listener_attached": payload.get("packet_listener_attached"),
            "wall_time": isoformat_z(),
        }
        self._sync_hardware_status_to_backend(backend_payload)

    def _handle_bus_error_event(self, payload: Mapping[str, Any]) -> None:
        """Log a BusManager error callback payload.

        Args:
            payload: Bus-error callback payload emitted by ``BusManager``.
        """
        log.warning("Gateway bus error event: %s", dict(payload))

    def _record_raw_telemetry_if_running(
        self,
        meta: Mapping[str, Any],
        packet: Any,
    ) -> dict[str, Any] | None:
        """Record a gateway telemetry_in raw event when raw history is active.

        Args:
            meta: Device metadata associated with the inbound packet.
            packet: Inbound live packet object.

        Returns:
            The materialized raw event dictionary when recording is active, or
            None when no raw run is active.
        """
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
                int(x) for x in list(getattr(packet, "data", [0, 0, 0, 0, 0, 0]) or [])
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
        """Record a gateway wire_command_out raw event when raw history is active.

        Args:
            device_id: Logical device identifier associated with the outbound
                packet, if known.
            packet: Outbound packet that was sent on the live bus.
        """
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
            "event_kind": "wire_command_out",
        }
        self.raw_history_manager.record_raw_event("wire_command_out", event)

    def _record_external_raw_event_if_running(
        self,
        *,
        stream_name: str,
        event: Mapping[str, Any],
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Record an externally supplied raw event into the active raw run.

        Args:
            stream_name: Raw stream name to append to.
            event: Raw event payload supplied by the caller.

        Returns:
            A tuple of ``(run_id, materialized_event)`` for the active raw run,
            or ``(None, None)`` when no raw run is active.
        """
        if not self.raw_history_manager.is_running:
            return None, None

        event_payload = dict(event)
        self.raw_history_manager.record_raw_event(stream_name, event_payload)

        current_run = self.raw_history_manager.current_run
        run_id = current_run.run_id if current_run is not None else None
        return run_id, event_payload

    def _handle_device_packet(
        self, meta: dict[str, Any], runtime: Any, packet: Any
    ) -> None:
        """Handle a live device packet from the registry listener path.

        The gateway records the packet into raw telemetry when a raw run is
        active, then forwards the packet and any materialized raw event payload
        to the backend ingest path.

        Args:
            meta: Static or runtime device metadata for the packet source.
            runtime: Device runtime object supplied by the registry listener.
            packet: Inbound live packet object.
        """
        del runtime

        materialized_raw_event: dict[str, Any] | None = None

        try:
            materialized_raw_event = self._record_raw_telemetry_if_running(meta, packet)
        except Exception:
            log.exception(
                "Gateway failed to record raw telemetry_in for %s", meta.get("id")
            )

        try:
            responses = self.backend_client.ingest_live_packet(
                meta=meta,
                packet=packet,
                raw_event=materialized_raw_event,
            )
            if responses:
                self._mark_backend_link_restored()
            else:
                self._mark_backend_link_failure(
                    "live packet forward returned no response"
                )
        except Exception as exc:
            self._mark_backend_link_failure(
                f"live packet forward failed for {meta.get('id')}: {exc}"
            )

    def _build_outbound_packet(self, payload: Mapping[str, Any]) -> DataPacket:
        """Build a DataPacket from the canonical gateway send_packet payload.

        Args:
            payload: Gateway ``send_packet`` payload.

        Returns:
            The normalized outbound ``DataPacket``.

        Raises:
            ValueError: If the payload ``data`` field contains more than six
                bytes.
        """
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
        """Resolve a live bus handle for an outbound device command.

        The lookup first prefers the runtime registered for ``device_id`` and
        then falls back to the first currently registered runtime that exposes a
        bus handle.

        Args:
            device_id: Requested logical device identifier, if any.

        Returns:
            The resolved live bus handle, or None when no registered runtime
            currently exposes one.
        """
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
        """Handle a gateway IPC request and yield reply messages.

        Supported requests cover handshake/status operations, raw/rawbak run
        lifecycle, external raw-event recording, live hardware initialization,
        ordinary packet sends, and relay-driven abort-latch messages.

        Args:
            client_id: Gateway server client identifier for the caller.
            message: Parsed gateway IPC request message.

        Yields:
            Gateway IPC reply messages for the request. Most request types yield
            exactly one reply, while ``hello`` yields both a hello-ack and a
            status message.

        Raises:
            ValueError: When a request payload is malformed or invalid.
            RuntimeError: When a required precondition is not met (e.g. live
                bus not connected).
        """
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

        if message.type == ABORT_RELAY_MESSAGE_TYPE:
            try:
                yield self._handle_abort_request_message(dict(message.payload))
            except Exception as exc:
                yield error_message(
                    code="gateway_abort_request_failed",
                    message=str(exc),
                )
            return

        if message.type == CLEAR_ABORT_LATCH_RELAY_MESSAGE_TYPE:
            try:
                yield self._handle_clear_abort_latch_request_message(
                    dict(message.payload)
                )
            except Exception as exc:
                yield error_message(
                    code="gateway_clear_abort_latch_failed",
                    message=str(exc),
                )
            return

        if message.type == "record_raw_event":
            try:
                payload = dict(message.payload)
                stream_name = str(payload["stream_name"])
                event_payload = payload.get("event")
                if not isinstance(event_payload, Mapping):
                    raise ValueError(
                        "record_raw_event requires 'event' to be a mapping"
                    )

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
                    current_run.started_wall_time
                    if current_run is not None
                    else isoformat_z()
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

                if self._abort_latched:
                    raise RuntimeError(
                        "gateway abort latch is active; refusing ordinary send_packet request"
                    )

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
