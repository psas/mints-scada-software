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

    def __init__(self, *, socket_path: str | Path, auto_ping_interval_ms: int = 2000) -> None:
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
        self._auto_ping_interval_ms = max(250, int(auto_ping_interval_ms))
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(self._auto_ping_interval_ms)
        self._heartbeat_timer.timeout.connect(self._send_heartbeat)

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._is_connected

    @property
    def last_hello_payload(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._last_hello_payload) if self._last_hello_payload is not None else None


    @property
    def last_disconnect_payload(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._last_disconnect_payload) if self._last_disconnect_payload is not None else None

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
    ) -> None:
        with self._lock:
            if self._is_connected:
                return

            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(str(self.socket_path))
            reader = sock.makefile("r", encoding="utf-8")
            writer = sock.makefile("w", encoding="utf-8")

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
            self._last_hello_payload = dict(hello_payload)

        self.connected.emit()
        self.send_message("hello", hello_payload)
        if not self._heartbeat_timer.isActive():
            self._heartbeat_timer.start()

    def disconnect_from_backend(self) -> None:
        self._stop_event.set()
        if self._heartbeat_timer.isActive():
            self._heartbeat_timer.stop()
        self._close_io()
        self._emit_disconnected_once(
            {
                "code": "client_disconnect",
                "message": "BackendClient disconnected locally",
            }
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
            if 'disconnect_reason' not in locals():
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
        with self._lock:
            if self._is_connected:
                self._is_connected = False
                self._last_disconnect_payload = dict(payload)
                should_emit = True

        if should_emit:
            self.disconnected.emit()
            self.disconnected_with_reason.emit(dict(payload))
