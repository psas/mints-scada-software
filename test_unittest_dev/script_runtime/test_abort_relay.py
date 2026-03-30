from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

from gui.abort_relay import AbortRelayServer, send_abort_request
from scripts.script_runtime.script_contract import (
    ABORT_COMMAND_NAME,
    ABORT_OPERATOR_ACTION,
    ABORT_REQUESTED_VIA,
)


def _json_line(payload: dict) -> bytes:
    return (json.dumps(payload) + "\n").encode("utf-8")


class FakeBackendServer:
    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path
        self.messages: list[dict] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._server: socket.socket | None = None

    def start(self) -> None:
        if self.socket_path.exists():
            self.socket_path.unlink()
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(self.socket_path))
        self._server.listen(8)
        self._server.settimeout(0.2)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._server is not None:
            try:
                self._server.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self.socket_path.exists():
            self.socket_path.unlink()

    def _serve(self) -> None:
        assert self._server is not None
        while not self._stop_event.is_set():
            try:
                conn, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                buffer = ""
                conn.settimeout(1.0)
                messages = []
                while len(messages) < 2:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buffer += chunk.decode("utf-8")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        if not line.strip():
                            continue
                        messages.append(json.loads(line))
                        if len(messages) == 2:
                            break
                if len(messages) != 2:
                    continue
                hello, request = messages
                assert hello["type"] == "hello"
                self.messages.append(request)
                if request["type"] == "operator_action":
                    response = {
                        "type": "operator_action_recorded",
                        "payload": dict(request["payload"]),
                    }
                elif request["type"] == "command_request":
                    response = {
                        "type": "command_result",
                        "payload": {
                            "success": True,
                            "command_name": request["payload"].get("command_name"),
                        },
                    }
                else:
                    response = {"type": "error", "payload": {"ok": False}}
                conn.sendall(_json_line(response))


def test_abort_relay_uses_contract_builders(tmp_path: Path) -> None:
    backend_socket = tmp_path / "backend.sock"
    relay_socket = tmp_path / "relay.sock"

    backend = FakeBackendServer(backend_socket)
    backend.start()

    relay = AbortRelayServer(relay_socket=relay_socket, backend_socket=backend_socket)
    relay_thread = threading.Thread(target=relay.serve_forever, daemon=True)
    relay_thread.start()

    deadline = time.time() + 2.0
    while not relay_socket.exists() and time.time() < deadline:
        time.sleep(0.02)

    try:
        result = send_abort_request(
            relay_socket=relay_socket,
            source_window_role="controller",
            source_window_kind="window",
            source_mode="live",
            command_payload={"command_kwargs": {"message": "operator clicked abort"}},
            operator_action={"note": "ui abort"},
        )
    finally:
        relay.stop()
        relay_thread.join(timeout=2.0)
        backend.stop()

    assert result["type"] == "abort_result"
    assert result["payload"]["ok"] is True
    assert len(backend.messages) == 2

    operator_request = backend.messages[0]
    command_request = backend.messages[1]

    assert operator_request["type"] == "operator_action"
    assert operator_request["payload"]["action"] == ABORT_OPERATOR_ACTION
    assert operator_request["payload"]["requested_via"] == ABORT_REQUESTED_VIA
    assert operator_request["payload"]["source_window_role"] == "controller"
    assert operator_request["payload"]["note"] == "ui abort"

    assert command_request["type"] == "command_request"
    assert command_request["payload"]["command_name"] == ABORT_COMMAND_NAME
    assert command_request["payload"]["requested_via"] == ABORT_REQUESTED_VIA
    assert command_request["payload"]["source_window_kind"] == "window"
    assert command_request["payload"]["source_mode"] == "live"
    assert command_request["payload"]["command_kwargs"]["message"] == "operator clicked abort"
