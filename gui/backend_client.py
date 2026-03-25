
from __future__ import annotations

import json
import os
import socket
import threading
from pathlib import Path
from typing import Any, Mapping

from PyQt5.QtCore import QObject, QTimer, pyqtSignal


class BackendClient(QObject):
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
        self._reconnect_initial_interval_ms = max(250, int(reconnect_initial_interval_ms))
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
        with self._lock:
            return self._is_connected

    @property
    def auto_reconnect_enabled(self) -> bool:
        with self._lock:
            return self._auto_reconnect_enabled

    @property
    def last_hello_payload(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._last_hello_payload) if self._last_hello_payload is not None else None

    @property
    def last_disconnect_payload(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._last_disconnect_payload) if self._last_disconnect_payload is not None else None

    def set_auto_reconnect_enabled(self, enabled: bool) -> None:
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

        self._complete_connection_handshake(hello_payload, was_reconnect=self._has_connected_once)
        return True

    def disconnect_from_backend(self) -> None:
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

    def send_message(self, message_type: str, payload: Mapping[str, Any] | None = None) -> None:
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
        self.send_message("ping", {})

    def request_backend_status(self) -> None:
        self.send_message("status_request", {})

    def request_full_state(self) -> None:
        self.send_message("request_full_state", {})

    def list_devices(self) -> None:
        self.send_message("list_devices", {})

    def initialize_live_hardware(self) -> None:
        self.send_message("initialize_live_hardware", {})

    def shutdown_live_hardware(self) -> None:
        self.send_message("shutdown_live_hardware", {})

    def start_run(self, payload: Mapping[str, Any]) -> None:
        self.send_message("start_run", payload)

    def finish_run(self, *, reason: str = "operator_stop") -> None:
        self.send_message("finish_run", {"reason": reason})

    def ingest_mock_telemetry(self, payload: Mapping[str, Any]) -> None:
        self.send_message("ingest_mock_telemetry", payload)

    def send_operator_action(self, payload: Mapping[str, Any]) -> None:
        self.send_message("operator_action", payload)

    def request_command(self, payload: Mapping[str, Any]) -> None:
        self.send_message("command_request", payload)

    def start_script(self, payload: Mapping[str, Any]) -> None:
        self.send_message("start_script", payload)

    def stop_script(self, *, reason: str = "operator_stop") -> None:
        self.send_message("stop_script", {"reason": reason})

    def hold_script(self, *, reason: str = "operator_hold") -> None:
        self.send_message("hold_script", {"reason": reason})

    def continue_script(self, *, reason: str = "operator_continue") -> None:
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

    def _complete_connection_handshake(self, hello_payload: Mapping[str, Any], *, was_reconnect: bool) -> None:
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
        should_emit = False
        payload = dict(reason or {})
        should_schedule_reconnect = False

        with self._lock:
            if self._is_connected:
                self._is_connected = False
                self._last_disconnect_payload = dict(payload)
                should_emit = True
                should_schedule_reconnect = self._auto_reconnect_enabled and not self._manual_disconnect

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
        payload = dict(reason or {})
        payload["_immediate"] = bool(immediate)
        self._schedule_reconnect_requested.emit(payload)

    def _handle_schedule_reconnect(self, payload: dict[str, Any]) -> None:
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
    """Small action-only surface for GUI windows in backend-first mode.

    This wrapper intentionally exposes semantic GUI actions instead of the raw
    socket client object, so window code does not become the owner of backend
    transport details.
    """

    def __init__(
        self,
        *,
        backend_client: BackendClient,
        mode: str,
        window_kind: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._backend_client = backend_client
        self.mode = str(mode)
        self.window_kind = str(window_kind)

    @property
    def is_connected(self) -> bool:
        return self._backend_client.is_connected

    @property
    def socket_path(self) -> Path:
        return self._backend_client.socket_path

    def request_backend_status(self) -> None:
        self._backend_client.request_backend_status()

    def request_full_state(self) -> None:
        self._backend_client.request_full_state()

    def list_devices(self) -> None:
        self._backend_client.list_devices()

    def refresh_runtime_views(self) -> None:
        """Refresh the main backend-backed runtime views for this window."""
        self.request_backend_status()
        self.request_full_state()
        self.list_devices()

    def initialize_live_hardware(self) -> None:
        self._backend_client.initialize_live_hardware()

    def shutdown_live_hardware(self) -> None:
        self._backend_client.shutdown_live_hardware()

    def start_run(self, payload: Mapping[str, Any]) -> None:
        self._backend_client.start_run(payload)

    def finish_run(self, *, reason: str = "operator_stop") -> None:
        self._backend_client.finish_run(reason=reason)

    def record_operator_action(self, action: str, **extra: Any) -> None:
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
        self._backend_client.stop_script(reason=reason)

    def hold_backend_script(self, *, reason: str = "operator_hold") -> None:
        self._backend_client.hold_script(reason=reason)

    def continue_backend_script(self, *, reason: str = "operator_continue") -> None:
        self._backend_client.continue_script(reason=reason)

    def reconnect_backend_now(self) -> None:
        self._backend_client.reconnect_now()
