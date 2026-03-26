from __future__ import annotations

import os
import socket
from pathlib import Path

from gateway.ipc_models import GatewayIPCMessage, decode_message, encode_message


class GatewayClient:
    """Minimal one-shot client for backend/gateway IPC."""

    def __init__(
        self,
        *,
        project_root: str | Path | None = None,
        socket_path: str | Path | None = None,
        timeout_s: float = 0.5,
    ) -> None:
        if project_root is None:
            project_root = Path(__file__).resolve().parents[1]
        else:
            project_root = Path(project_root).expanduser().resolve()

        if socket_path is None:
            socket_path = project_root / ".gateway_service.sock"
        else:
            socket_path = Path(socket_path).expanduser().resolve()

        self.project_root = project_root
        self.socket_path = Path(socket_path).expanduser().resolve()
        self.timeout_s = timeout_s

    def _read_one_line(self, conn: socket.socket) -> bytes | None:
        buffer = bytearray()
        while True:
            chunk = conn.recv(1)
            if not chunk:
                return bytes(buffer) if buffer else None
            if chunk == b"\n":
                return bytes(buffer)
            buffer.extend(chunk)

    def request(
        self,
        message_type: str,
        *,
        payload: dict | None = None,
        expected_responses: int = 1,
    ) -> list[GatewayIPCMessage]:
        if not self.socket_path.exists():
            return []

        request = GatewayIPCMessage(type=message_type, payload=payload or {})
        responses: list[GatewayIPCMessage] = []

        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(self.timeout_s)
        try:
            conn.connect(str(self.socket_path))
            conn.sendall(encode_message(request) + b"\n")

            for _ in range(expected_responses):
                line = self._read_one_line(conn)
                if not line:
                    break
                responses.append(decode_message(line))
        except (OSError, TimeoutError):
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return responses

    def hello(
        self,
        *,
        service_name: str,
        backend_socket_path: str,
    ) -> list[GatewayIPCMessage]:
        return self.request(
            "hello",
            payload={
                "service_name": service_name,
                "pid": os.getpid(),
                "backend_socket_path": backend_socket_path,
            },
            expected_responses=2,
        )

    def ping(self) -> list[GatewayIPCMessage]:
        return self.request("ping", expected_responses=1)

    def status_request(self) -> list[GatewayIPCMessage]:
        return self.request("status_request", expected_responses=1)