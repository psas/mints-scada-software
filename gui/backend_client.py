# gui/backend_client.py

"""Qt backend client and semantic GUI action wrapper for backend-first mode.

This module provides the GUI-side Unix-socket client used to talk to the
backend service and fan backend IPC messages into Qt signals. It also exposes
a smaller action-oriented wrapper so GUI windows can request backend work
without owning transport details directly.
"""

from __future__ import annotations

import json
import os
import socket
import threading
from pathlib import Path
from typing import Any, Mapping

from PyQt5.QtCore import QObject, QTimer, pyqtSignal


class BackendClient(QObject):
    """Manage a GUI-side connection to the backend IPC socket.

    The client owns the Unix-domain socket, a background reader thread, a
    heartbeat timer, and optional reconnect scheduling. Incoming backend
    messages are decoded and re-emitted through typed Qt signals so window code
    can subscribe to backend state, structured events, command results, and
    connection lifecycle changes.
    """

    connected = pyqtSignal()
    disconnected = pyqtSignal()
    disconnected_with_reason = pyqtSignal(dict)
    reconnect_scheduled = pyqtSignal(dict)
    reconnect_attempt_started = pyqtSignal(dict)
    reconnect_succeeded = pyqtSignal(dict)
    hello_ack_received = pyqtSignal(dict)
    backend_status_received = pyqtSignal(dict)
    state_snapshot_received = pyqtSignal(dict)
    structured_event_received = pyqtSignal(dict)
    device_inventory_received = pyqtSignal(dict)
    hardware_status_received = pyqtSignal(dict)
    run_status_received = pyqtSignal(dict)
    operator_action_recorded_received = pyqtSignal(dict)
    command_result_received = pyqtSignal(dict)
    script_status_received = pyqtSignal(dict)
    error_received = pyqtSignal(dict)
    raw_message_received = pyqtSignal(str, dict)

    _schedule_reconnect_requested = pyqtSignal(dict)

    def __init__(
        self,
        *,
        socket_path: str | Path,
        auto_ping_interval_ms: int = 2000,
        auto_reconnect_enabled: bool = False,
        reconnect_initial_interval_ms: int = 750,
        reconnect_max_interval_ms: int = 5000,
    ) -> None:
        """Initialize the backend client and its timers.

        Args:
            socket_path: Filesystem path to the backend Unix-domain socket.
            auto_ping_interval_ms: Heartbeat interval used while connected.
            auto_reconnect_enabled: Whether disconnects should schedule
                reconnect attempts automatically.
            reconnect_initial_interval_ms: Initial reconnect delay used for
                backoff scheduling.
            reconnect_max_interval_ms: Maximum reconnect delay used for
                backoff scheduling.
        """
        super().__init__()
        self.socket_path = Path(socket_path).expanduser().resolve()

        self._lock = threading.RLock()
        self._socket: socket.socket | None = None
        self._reader = None
        self._writer = None
        self._reader_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._is_connected = False
        self._last_hello_payload: dict[str, Any] | None = None
        self._last_disconnect_payload: dict[str, Any] | None = None
        self._saved_connect_kwargs: dict[str, Any] | None = None
        self._manual_disconnect = False
        self._has_connected_once = False
        self._reconnect_attempt_count = 0
        self._reconnect_in_progress = False

        self._auto_ping_interval_ms = max(250, int(auto_ping_interval_ms))
        self._auto_reconnect_enabled = bool(auto_reconnect_enabled)
        self._reconnect_initial_interval_ms = max(
            250, int(reconnect_initial_interval_ms)
        )
        self._reconnect_max_interval_ms = max(
            self._reconnect_initial_interval_ms,
            int(reconnect_max_interval_ms),
        )
        self._next_reconnect_interval_ms = self._reconnect_initial_interval_ms

        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(self._auto_ping_interval_ms)
        self._heartbeat_timer.timeout.connect(self._send_heartbeat)

        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._attempt_reconnect)

        self._schedule_reconnect_requested.connect(self._handle_schedule_reconnect)

    @property
    def is_connected(self) -> bool:
        """Return whether the backend socket is currently open.

        Returns:
            True when the client considers the backend connection active.
        """
        with self._lock:
            return self._is_connected

    @property
    def auto_reconnect_enabled(self) -> bool:
        """Return whether automatic reconnect scheduling is enabled.

        Returns:
            True when disconnect handling may schedule reconnect attempts.
        """
        with self._lock:
            return self._auto_reconnect_enabled

    @property
    def last_hello_payload(self) -> dict[str, Any] | None:
        """Return the most recent hello payload sent or prepared by the client.

        Returns:
            A shallow copy of the last hello payload, or None when no hello has
            been prepared yet.
        """
        with self._lock:
            return (
                dict(self._last_hello_payload)
                if self._last_hello_payload is not None
                else None
            )

    @property
    def last_disconnect_payload(self) -> dict[str, Any] | None:
        """Return the most recent disconnect reason payload.

        Returns:
            A shallow copy of the last disconnect payload, or None when no
            disconnect has been recorded yet.
        """
        with self._lock:
            return (
                dict(self._last_disconnect_payload)
                if self._last_disconnect_payload is not None
                else None
            )

    def set_auto_reconnect_enabled(self, enabled: bool) -> None:
        """Enable or disable automatic reconnect scheduling.

        Disabling reconnect also cancels any reconnect timer that is already
        pending.

        Args:
            enabled: Whether reconnect attempts should be scheduled after
                unexpected disconnects.
        """
        with self._lock:
            self._auto_reconnect_enabled = bool(enabled)
            if not self._auto_reconnect_enabled and self._reconnect_timer.isActive():
                self._reconnect_timer.stop()

    def connect_to_backend(
        self,
        *,
        client_name: str = "user-gui",
        logical_client_id: str | None = None,
        window_role: str | None = None,
        session_id: str | None = None,
        mode: str | None = None,
        window_kind: str | None = None,
        pid: int | None = None,
        launcher_pid: int | None = None,
        selected_test: str | None = None,
        hello_extra: Mapping[str, Any] | None = None,
        allow_deferred_reconnect: bool = False,
    ) -> bool:
        """Open the backend socket and send the initial hello handshake.

        The connection parameters are saved so later reconnect attempts can
        rebuild the same hello payload. When the initial connection fails and
        reconnect is allowed, this method emits the disconnect reason and
        schedules an immediate reconnect instead of raising.

        Args:
            client_name: Client name advertised in the hello payload.
            logical_client_id: Stable logical client identifier for the backend.
            window_role: Window role reported to the backend.
            session_id: Session identifier reported to the backend.
            mode: Runtime mode reported to the backend, such as live or
                playback.
            window_kind: GUI window kind reported to the backend.
            pid: Process identifier to report in the hello payload. Defaults to
                the current process id.
            launcher_pid: Launcher process id to report in the hello payload.
            selected_test: Selected test name to include in the hello payload.
            hello_extra: Additional hello payload fields that should be merged
                without overriding canonical fields.
            allow_deferred_reconnect: Whether an initial connection failure may
                be converted into a scheduled reconnect instead of an exception.

        Returns:
            True when the connection opens and the hello handshake is sent.
            False when the initial connection fails but reconnect was scheduled.

        Raises:
            Exception: Propagates the socket-open failure when reconnect is not
                allowed for the initial connection attempt.
        """
        connect_kwargs: dict[str, Any] = {
            "client_name": client_name,
            "logical_client_id": logical_client_id,
            "window_role": window_role,
            "session_id": session_id,
            "mode": mode,
            "window_kind": window_kind,
            "pid": pid,
            "launcher_pid": launcher_pid,
            "selected_test": selected_test,
            "hello_extra": dict(hello_extra or {}),
        }
        hello_payload = self._build_hello_payload(
            client_name=client_name,
            logical_client_id=logical_client_id,
            window_role=window_role,
            session_id=session_id,
            mode=mode,
            window_kind=window_kind,
            pid=pid,
            launcher_pid=launcher_pid,
            selected_test=selected_test,
            hello_extra=hello_extra,
        )

        with self._lock:
            self._saved_connect_kwargs = dict(connect_kwargs)
            self._last_hello_payload = dict(hello_payload)
            self._manual_disconnect = False

        try:
            self._open_connection()
        except Exception as exc:
            if self.auto_reconnect_enabled or allow_deferred_reconnect:
                payload = {
                    "code": "backend_connect_failed",
                    "message": f"Backend connection failed: {exc}",
                    "socket_path": str(self.socket_path),
                }
                with self._lock:
                    self._last_disconnect_payload = dict(payload)
                self.disconnected_with_reason.emit(dict(payload))
                self._schedule_reconnect_from_any_thread(payload, immediate=True)
                return False
            raise

        self._complete_connection_handshake(
            hello_payload, was_reconnect=self._has_connected_once
        )
        return True

    def disconnect_from_backend(self) -> None:
        """Close the backend connection and stop heartbeat or reconnect timers.

        This marks the disconnect as manual so automatic reconnect scheduling is
        suppressed for the close path initiated by the GUI.
        """
        with self._lock:
            self._manual_disconnect = True
        self._stop_event.set()
        if self._heartbeat_timer.isActive():
            self._heartbeat_timer.stop()
        if self._reconnect_timer.isActive():
            self._reconnect_timer.stop()
        self._close_io()
        self._emit_disconnected_once(
            {
                "code": "client_disconnect",
                "message": "BackendClient disconnected locally",
            }
        )

    def reconnect_now(self) -> None:
        """Request an immediate reconnect attempt using the saved hello parameters.

        The request is ignored until the client has saved connection parameters
        from a previous connect attempt.
        """
        with self._lock:
            if self._saved_connect_kwargs is None:
                return
        self._schedule_reconnect_from_any_thread(
            {
                "code": "manual_reconnect_request",
                "message": "Manual backend reconnect requested",
            },
            immediate=True,
        )

    def send_message(
        self, message_type: str, payload: Mapping[str, Any] | None = None
    ) -> None:
        """Encode and send a backend IPC message over the active socket.

        Args:
            message_type: Backend IPC message type.
            payload: Message payload to serialize as JSON.

        Raises:
            RuntimeError: The client is not currently connected.
        """
        with self._lock:
            if not self._is_connected or self._writer is None:
                raise RuntimeError("BackendClient is not connected")

            message = {
                "type": message_type,
                "payload": dict(payload or {}),
            }
            self._writer.write(json.dumps(message, ensure_ascii=False, sort_keys=False))
            self._writer.write("\n")
            self._writer.flush()

    def ping(self) -> None:
        """Send a backend heartbeat ping."""
        self.send_message("ping", {})

    def request_backend_status(self) -> None:
        """Request the backend status snapshot."""
        self.send_message("status_request", {})

    def request_full_state(self) -> None:
        """Request the full authoritative backend runtime state."""
        self.send_message("request_full_state", {})

    def list_devices(self) -> None:
        """Request the backend device inventory snapshot."""
        self.send_message("list_devices", {})

    def initialize_live_hardware(self) -> None:
        """Request live hardware initialization through the backend."""
        self.send_message("initialize_live_hardware", {})

    def shutdown_live_hardware(self) -> None:
        """Request live hardware shutdown through the backend."""
        self.send_message("shutdown_live_hardware", {})

    def start_run(self, payload: Mapping[str, Any]) -> None:
        """Request backend run startup with the provided run metadata.

        Args:
            payload: Backend ``start_run`` payload.
        """
        self.send_message("start_run", payload)

    def finish_run(self, *, reason: str = "operator_stop") -> None:
        """Request backend run completion.

        Args:
            reason: Finish reason sent to the backend.
        """
        self.send_message("finish_run", {"reason": reason})

    def ingest_mock_telemetry(self, payload: Mapping[str, Any]) -> None:
        """Send mock telemetry into the backend ingest path.

        Args:
            payload: Backend ``ingest_mock_telemetry`` payload.
        """
        self.send_message("ingest_mock_telemetry", payload)

    def send_operator_action(self, payload: Mapping[str, Any]) -> None:
        """Record an operator action through the backend.

        Args:
            payload: Backend ``operator_action`` payload.
        """
        self.send_message("operator_action", payload)

    def request_command(self, payload: Mapping[str, Any]) -> None:
        """Submit a backend command request.

        Args:
            payload: Backend ``command_request`` payload.
        """
        self.send_message("command_request", payload)

    def start_script(self, payload: Mapping[str, Any]) -> None:
        """Request backend-owned script startup.

        Args:
            payload: Backend ``start_script`` payload.
        """
        self.send_message("start_script", payload)

    def stop_script(self, *, reason: str = "operator_stop") -> None:
        """Request backend script stop.

        Args:
            reason: Stop reason sent to the backend.
        """
        self.send_message("stop_script", {"reason": reason})

    def hold_script(self, *, reason: str = "operator_hold") -> None:
        """Request backend script hold.

        Args:
            reason: Hold reason sent to the backend.
        """
        self.send_message("hold_script", {"reason": reason})

    def continue_script(self, *, reason: str = "operator_continue") -> None:
        """Request backend script resume.

        Args:
            reason: Continue reason sent to the backend.
        """
        self.send_message("continue_script", {"reason": reason})

    def _build_hello_payload(
        self,
        *,
        client_name: str,
        logical_client_id: str | None,
        window_role: str | None,
        session_id: str | None,
        mode: str | None,
        window_kind: str | None,
        pid: int | None,
        launcher_pid: int | None,
        selected_test: str | None,
        hello_extra: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Build the hello payload for the backend handshake.

        Canonical hello fields are populated first, then ``hello_extra`` is
        merged without overriding fields already set by this client.

        Args:
            client_name: Client name advertised to the backend.
            logical_client_id: Stable logical client identifier.
            window_role: Window role reported to the backend.
            session_id: Session identifier reported to the backend.
            mode: Runtime mode reported to the backend.
            window_kind: GUI window kind reported to the backend.
            pid: Process identifier to report, or None to use the current
                process id.
            launcher_pid: Launcher process id to include when known.
            selected_test: Selected test name to include when known.
            hello_extra: Additional hello fields to merge.

        Returns:
            The hello payload dictionary that will be sent to the backend.
        """
        payload: dict[str, Any] = {
            "client_name": client_name,
            "pid": int(os.getpid() if pid is None else pid),
        }

        if logical_client_id:
            payload["logical_client_id"] = logical_client_id
        if window_role:
            payload["window_role"] = window_role
        if session_id:
            payload["session_id"] = session_id
        if mode:
            payload["mode"] = mode
        if window_kind:
            payload["window_kind"] = window_kind
        if launcher_pid is not None:
            payload["launcher_pid"] = int(launcher_pid)
        if selected_test:
            payload["selected_test"] = selected_test

        if hello_extra is not None:
            for key, value in hello_extra.items():
                if key not in payload:
                    payload[key] = value

        return payload

    def _open_connection(self) -> None:
        """Open the backend Unix-domain socket and start the reader thread.

        Raises:
            Exception: Propagates socket or file-wrapper creation failures after
                cleaning up the partially opened socket.
        """
        with self._lock:
            if self._is_connected:
                return

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(str(self.socket_path))
            reader = sock.makefile("r", encoding="utf-8")
            writer = sock.makefile("w", encoding="utf-8")
        except Exception:
            try:
                sock.close()
            except Exception:
                pass
            raise

        with self._lock:
            self._socket = sock
            self._reader = reader
            self._writer = writer
            self._stop_event.clear()
            self._is_connected = True

            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                name="gui-backend-client-reader",
                daemon=True,
            )
            self._reader_thread.start()

    def _complete_connection_handshake(
        self, hello_payload: Mapping[str, Any], *, was_reconnect: bool
    ) -> None:
        """Finalize a successful socket open and send the hello message.

        This resets reconnect backoff state, marks the client connected for the
        new session, emits the generic connected signal, and optionally emits a
        reconnect-success signal for restored connections.

        Args:
            hello_payload: Hello payload to send to the backend.
            was_reconnect: Whether this handshake followed at least one prior
                successful connection.
        """
        if self._reconnect_timer.isActive():
            self._reconnect_timer.stop()

        with self._lock:
            self._next_reconnect_interval_ms = self._reconnect_initial_interval_ms
            self._reconnect_attempt_count = 0
            self._reconnect_in_progress = False
            self._manual_disconnect = False
            self._last_hello_payload = dict(hello_payload)
            self._last_disconnect_payload = None
            self._has_connected_once = True

        self.connected.emit()
        self.send_message("hello", hello_payload)
        if not self._heartbeat_timer.isActive():
            self._heartbeat_timer.start()

        if was_reconnect:
            self.reconnect_succeeded.emit(
                {
                    "code": "backend_reconnected",
                    "message": "Backend connection restored",
                    "socket_path": str(self.socket_path),
                }
            )

    def _send_heartbeat(self) -> None:
        """Send the periodic backend heartbeat when connected.

        Heartbeat send failures are treated as disconnects and routed through
        the normal disconnect handling path.
        """
        if not self.is_connected:
            return
        try:
            self.ping()
        except Exception as exc:
            self._emit_disconnected_once(
                {
                    "code": "heartbeat_failed",
                    "message": f"Backend heartbeat failed: {exc}",
                }
            )

    def _reader_loop(self) -> None:
        """Read backend JSON messages, decode them, and emit Qt signals.

        The loop treats each line as one JSON message, emits ``error_received``
        for malformed input, and routes valid decoded messages through
        ``raw_message_received`` plus the typed dispatch path. When the stream
        ends or the reader fails, the connection is closed and a single
        disconnect event is emitted.
        """
        try:
            reader = self._reader
            if reader is None:
                return

            for raw_line in reader:
                if self._stop_event.is_set():
                    break

                raw_line = raw_line.strip()
                if not raw_line:
                    continue

                try:
                    decoded = json.loads(raw_line)
                except Exception as exc:
                    self.error_received.emit(
                        {
                            "code": "invalid_backend_json",
                            "message": f"Failed to decode backend JSON: {exc}",
                            "raw": raw_line,
                        }
                    )
                    continue

                if not isinstance(decoded, dict):
                    self.error_received.emit(
                        {
                            "code": "invalid_backend_message",
                            "message": "Backend message must decode to an object",
                            "raw": raw_line,
                        }
                    )
                    continue

                message_type = decoded.get("type")
                payload = decoded.get("payload", {})

                if not isinstance(message_type, str):
                    self.error_received.emit(
                        {
                            "code": "invalid_backend_message_type",
                            "message": "Backend message missing string 'type'",
                            "raw": raw_line,
                        }
                    )
                    continue

                if not isinstance(payload, dict):
                    payload = {}

                self.raw_message_received.emit(message_type, dict(payload))
                self._dispatch_message(message_type, dict(payload))
        except Exception as exc:
            disconnect_reason = {
                "code": "backend_reader_failed",
                "message": str(exc),
            }
            self.error_received.emit(dict(disconnect_reason))
        finally:
            self._close_io()
            if "disconnect_reason" not in locals():
                disconnect_reason = {
                    "code": "backend_connection_closed",
                    "message": "Backend connection closed",
                }
            self._emit_disconnected_once(disconnect_reason)

    def _dispatch_message(self, message_type: str, payload: dict[str, Any]) -> None:
        """Emit the typed Qt signal for a decoded backend message.

        Unknown message types are ignored after the raw-message signal has
        already been emitted by the reader loop.

        Args:
            message_type: Decoded backend message type.
            payload: Decoded backend payload dictionary.
        """
        if message_type == "hello_ack":
            self.hello_ack_received.emit(payload)
        elif message_type == "backend_status":
            self.backend_status_received.emit(payload)
        elif message_type == "state_snapshot":
            self.state_snapshot_received.emit(payload)
        elif message_type == "structured_event":
            self.structured_event_received.emit(payload)
        elif message_type == "device_inventory":
            self.device_inventory_received.emit(payload)
        elif message_type == "hardware_status":
            self.hardware_status_received.emit(payload)
        elif message_type == "run_status":
            self.run_status_received.emit(payload)
        elif message_type == "operator_action_recorded":
            self.operator_action_recorded_received.emit(payload)
        elif message_type == "command_result":
            self.command_result_received.emit(payload)
        elif message_type == "script_status":
            self.script_status_received.emit(payload)
        elif message_type == "error":
            self.error_received.emit(payload)

    def _close_io(self) -> None:
        """Close the current socket and text wrappers and clear local handles."""
        with self._lock:
            writer = self._writer
            reader = self._reader
            sock = self._socket

            self._writer = None
            self._reader = None
            self._socket = None

        try:
            if writer is not None:
                writer.close()
        except Exception:
            pass

        try:
            if reader is not None:
                reader.close()
        except Exception:
            pass

        try:
            if sock is not None:
                sock.close()
        except Exception:
            pass

    def _emit_disconnected_once(self, reason: Mapping[str, Any] | None = None) -> None:
        """Mark the client disconnected and emit disconnect signals once.

        Automatic reconnect scheduling is triggered only for unexpected
        disconnects while reconnect is enabled.

        Args:
            reason: Disconnect reason payload to cache and emit.
        """
        should_emit = False
        payload = dict(reason or {})
        should_schedule_reconnect = False

        with self._lock:
            if self._is_connected:
                self._is_connected = False
                self._last_disconnect_payload = dict(payload)
                should_emit = True
                should_schedule_reconnect = (
                    self._auto_reconnect_enabled and not self._manual_disconnect
                )

        if should_emit:
            self.disconnected.emit()
            self.disconnected_with_reason.emit(dict(payload))

        if should_schedule_reconnect:
            self._schedule_reconnect_from_any_thread(payload, immediate=False)

    def _schedule_reconnect_from_any_thread(
        self,
        reason: Mapping[str, Any] | None,
        *,
        immediate: bool,
    ) -> None:
        """Forward a reconnect scheduling request through a Qt signal.

        This keeps reconnect timer manipulation on the Qt-owning thread even
        when the request originates from the reader thread.

        Args:
            reason: Reconnect reason payload.
            immediate: Whether the reconnect timer should fire without delay.
        """
        payload = dict(reason or {})
        payload["_immediate"] = bool(immediate)
        self._schedule_reconnect_requested.emit(payload)

    def _handle_schedule_reconnect(self, payload: dict[str, Any]) -> None:
        """Schedule the reconnect timer and emit reconnect metadata.

        Args:
            payload: Reconnect reason payload forwarded through
                ``_schedule_reconnect_requested``. The internal ``_immediate``
                flag is consumed here to choose the timer delay.
        """
        with self._lock:
            if not self._auto_reconnect_enabled or self._manual_disconnect:
                return
            if self._saved_connect_kwargs is None:
                return
            if self._is_connected:
                return

            immediate = bool(payload.pop("_immediate", False))
            interval_ms = 0 if immediate else self._next_reconnect_interval_ms
            self._reconnect_attempt_count += 1
            self._reconnect_in_progress = True
            if not immediate:
                self._next_reconnect_interval_ms = min(
                    self._next_reconnect_interval_ms * 2,
                    self._reconnect_max_interval_ms,
                )

        scheduled_payload = {
            "code": str(payload.get("code") or "backend_reconnect_scheduled"),
            "message": str(payload.get("message") or "Backend reconnect scheduled"),
            "socket_path": str(self.socket_path),
            "attempt_count": self._reconnect_attempt_count,
            "retry_in_ms": interval_ms,
        }
        self.reconnect_scheduled.emit(dict(scheduled_payload))
        self._reconnect_timer.start(interval_ms)

    def _attempt_reconnect(self) -> None:
        """Attempt one reconnect using the saved hello parameters.

        A failed reconnect is routed back into the scheduling path so backoff
        continues. A successful reconnect reuses the normal handshake
        completion logic.
        """
        with self._lock:
            if self._saved_connect_kwargs is None or self._is_connected:
                self._reconnect_in_progress = False
                return
            connect_kwargs = dict(self._saved_connect_kwargs)
            hello_payload = self._build_hello_payload(
                client_name=str(connect_kwargs.get("client_name") or "user-gui"),
                logical_client_id=connect_kwargs.get("logical_client_id"),
                window_role=connect_kwargs.get("window_role"),
                session_id=connect_kwargs.get("session_id"),
                mode=connect_kwargs.get("mode"),
                window_kind=connect_kwargs.get("window_kind"),
                pid=connect_kwargs.get("pid"),
                launcher_pid=connect_kwargs.get("launcher_pid"),
                selected_test=connect_kwargs.get("selected_test"),
                hello_extra=connect_kwargs.get("hello_extra"),
            )
            attempt_number = self._reconnect_attempt_count or 1

        self.reconnect_attempt_started.emit(
            {
                "code": "backend_reconnect_attempt",
                "message": "Attempting backend reconnect",
                "socket_path": str(self.socket_path),
                "attempt_count": attempt_number,
            }
        )

        try:
            self._open_connection()
        except Exception as exc:
            self._handle_schedule_reconnect(
                {
                    "code": "backend_reconnect_failed",
                    "message": f"Backend reconnect failed: {exc}",
                    "socket_path": str(self.socket_path),
                }
            )
            return

        self._complete_connection_handshake(hello_payload, was_reconnect=True)


class GuiBackendActionAPI(QObject):
    """Expose semantic GUI actions on top of ``BackendClient``.

    This wrapper keeps window code focused on higher-level GUI actions such as
    requesting runtime refreshes, issuing commands, and controlling scripts,
    instead of constructing raw backend transport calls directly.
    """

    def __init__(
        self,
        *,
        backend_client: BackendClient,
        mode: str,
        window_kind: str,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the GUI action wrapper.

        Args:
            backend_client: Connected backend client used to send requests.
            mode: GUI mode associated with this action surface.
            window_kind: Window kind associated with this action surface.
            parent: Optional Qt parent object.
        """
        super().__init__(parent)
        self._backend_client = backend_client
        self.mode = str(mode)
        self.window_kind = str(window_kind)

    @property
    def is_connected(self) -> bool:
        """Return whether the wrapped backend client is connected.

        Returns:
            True when the underlying backend client is connected.
        """
        return self._backend_client.is_connected

    @property
    def socket_path(self) -> Path:
        """Return the backend socket path used by the wrapped client.

        Returns:
            The resolved backend Unix-domain socket path.
        """
        return self._backend_client.socket_path

    def request_backend_status(self) -> None:
        """Request backend status through the wrapped client."""
        self._backend_client.request_backend_status()

    def request_full_state(self) -> None:
        """Request the full backend runtime state through the wrapped client."""
        self._backend_client.request_full_state()

    def list_devices(self) -> None:
        """Request the backend device inventory through the wrapped client."""
        self._backend_client.list_devices()

    def refresh_runtime_views(self) -> None:
        """Refresh the main backend-backed runtime views for this window.

        This requests backend status, the full runtime state snapshot, and the
        current device inventory in one semantic call.
        """
        self.request_backend_status()
        self.request_full_state()
        self.list_devices()

    def initialize_live_hardware(self) -> None:
        """Request live hardware initialization."""
        self._backend_client.initialize_live_hardware()

    def shutdown_live_hardware(self) -> None:
        """Request live hardware shutdown."""
        self._backend_client.shutdown_live_hardware()

    def start_run(self, payload: Mapping[str, Any]) -> None:
        """Request backend run startup.

        Args:
            payload: Backend ``start_run`` payload.
        """
        self._backend_client.start_run(payload)

    def finish_run(self, *, reason: str = "operator_stop") -> None:
        """Request backend run completion.

        Args:
            reason: Finish reason sent to the backend.
        """
        self._backend_client.finish_run(reason=reason)

    def record_operator_action(self, action: str, **extra: Any) -> None:
        """Record a semantic operator action through the backend.

        Args:
            action: Operator action name.
            **extra: Additional operator-action fields to include in the
                backend payload.
        """
        payload = {"action": action, **extra}
        self._backend_client.send_operator_action(payload)

    def request_backend_command(
        self,
        command_name: str,
        *,
        device_id: str | None = None,
        command_args: list[Any] | None = None,
        command_kwargs: Mapping[str, Any] | None = None,
        mock_only: bool = False,
        operator_action: Mapping[str, Any] | None = None,
    ) -> None:
        """Build and submit a backend ``command_request`` payload.

        Args:
            command_name: Canonical backend command name.
            device_id: Optional device identifier targeted by the command.
            command_args: Optional positional command arguments.
            command_kwargs: Optional keyword-style command arguments.
            mock_only: Whether the backend should treat the request as mock-only.
            operator_action: Optional operator-action payload to attach to the
                command request.
        """
        payload: dict[str, Any] = {
            "command_name": command_name,
            "mock_only": bool(mock_only),
        }
        if device_id is not None:
            payload["device_id"] = str(device_id)
        if command_args is not None:
            payload["command_args"] = list(command_args)
        if command_kwargs is not None:
            payload["command_kwargs"] = dict(command_kwargs)
        if operator_action is not None:
            payload["operator_action"] = dict(operator_action)
        self._backend_client.request_command(payload)

    def start_backend_script(
        self,
        *,
        name: str,
        command: list[str] | None = None,
        inline_python: str | None = None,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        """Build and submit a backend ``start_script`` request.

        Args:
            name: Script name recorded by the backend.
            command: Optional subprocess command vector for the script runner.
            inline_python: Optional inline Python source for the script runner.
            cwd: Optional working directory for script execution.
            env: Optional environment overrides for script execution.
        """
        payload: dict[str, Any] = {"name": str(name)}
        if command is not None:
            payload["command"] = list(command)
        if inline_python is not None:
            payload["inline_python"] = str(inline_python)
        if cwd is not None:
            payload["cwd"] = str(cwd)
        if env is not None:
            payload["env"] = {str(key): str(value) for key, value in env.items()}
        self._backend_client.start_script(payload)

    def stop_backend_script(self, *, reason: str = "operator_stop") -> None:
        """Request backend script stop.

        Args:
            reason: Stop reason sent to the backend.
        """
        self._backend_client.stop_script(reason=reason)

    def hold_backend_script(self, *, reason: str = "operator_hold") -> None:
        """Request backend script hold.

        Args:
            reason: Hold reason sent to the backend.
        """
        self._backend_client.hold_script(reason=reason)

    def continue_backend_script(self, *, reason: str = "operator_continue") -> None:
        """Request backend script resume.

        Args:
            reason: Continue reason sent to the backend.
        """
        self._backend_client.continue_script(reason=reason)

    def reconnect_backend_now(self) -> None:
        """Request an immediate reconnect through the wrapped backend client."""
        self._backend_client.reconnect_now()
