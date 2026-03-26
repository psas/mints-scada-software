from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

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
                "backend_socket_path": backend_socket_path,
            },
            expected_responses=2,
        )

    def ping(self) -> list[GatewayIPCMessage]:
        return self.request("ping", expected_responses=1)

    def status_request(self) -> list[GatewayIPCMessage]:
        return self.request("status_request", expected_responses=1)

    def initialize_live_hardware(self) -> list[GatewayIPCMessage]:
        return self.request("initialize_live_hardware", expected_responses=1)

    def shutdown_live_hardware(self) -> list[GatewayIPCMessage]:
        return self.request("shutdown_live_hardware", expected_responses=1)

    def send_packet(
        self,
        *,
        device_id: str,
        packet: Any,
    ) -> list[GatewayIPCMessage]:
        packet_id = getattr(packet, "id", None)
        if packet_id is None:
            raise ValueError("Outbound packet is missing 'id'")

        return self.request(
            "send_packet",
            payload={
                "device_id": device_id,
                "id": int(packet_id),
                "seq": int(getattr(packet, "seq", 1)),
                "cmd": int(getattr(packet, "cmd", 1)),
                "reply": bool(getattr(packet, "reply", False)),
                "err": bool(getattr(packet, "err", False)),
                "rsvd": bool(getattr(packet, "rsvd", False)),
                "data": [int(x) for x in list(getattr(packet, "data", []) or [])],
            },
            expected_responses=1,
        )

    def start_run(
        self,
        *,
        run_id: str,
        test_name: str,
        mode: str,
        operator: str | None = None,
        profile_name: str | None = None,
        notes: str | None = None,
        software_git_commit: str | None = None,
        software_branch: str | None = None,
        device_map_version: str | None = None,
        svg_version: str | None = None,
        bus_config: dict | None = None,
        clock_info: dict | None = None,
        extra_metadata: dict | None = None,
    ) -> list[GatewayIPCMessage]:
        return self.request(
            "start_run",
            payload={
                "run_id": run_id,
                "test_name": test_name,
                "mode": mode,
                "operator": operator,
                "profile_name": profile_name,
                "notes": notes,
                "software_git_commit": software_git_commit,
                "software_branch": software_branch,
                "device_map_version": device_map_version,
                "svg_version": svg_version,
                "bus_config": dict(bus_config or {}),
                "clock_info": dict(clock_info or {}),
                "extra_metadata": dict(extra_metadata or {}),
            },
            expected_responses=1,
        )

    def finish_run(
        self,
        *,
        run_id: str,
        reason: str,
    ) -> list[GatewayIPCMessage]:
        return self.request(
            "finish_run",
            payload={
                "run_id": run_id,
                "reason": reason,
            },
            expected_responses=1,
        )
    
    def record_raw_event(
        self,
        *,
        stream_name: str,
        event: dict,
    ) -> list[GatewayIPCMessage]:
        return self.request(
            "record_raw_event",
            payload={
                "stream_name": stream_name,
                "event": dict(event),
            },
            expected_responses=1,
        )
