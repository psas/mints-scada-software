from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any, Mapping


class BackendIPCClient:
    """Minimal one-shot client for gateway -> backend IPC."""

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
            socket_path = project_root / ".backend_service.sock"
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
        payload: Mapping[str, Any] | None = None,
        expected_responses: int = 1,
    ) -> list[dict[str, Any]]:
        if not self.socket_path.exists():
            return []

        request_bytes = json.dumps(
            {
                "type": message_type,
                "payload": dict(payload or {}),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8") + b"\n"

        responses: list[dict[str, Any]] = []
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(self.timeout_s)

        try:
            conn.connect(str(self.socket_path))
            conn.sendall(request_bytes)

            for _ in range(expected_responses):
                line = self._read_one_line(conn)
                if not line:
                    break
                data = json.loads(line.decode("utf-8"))
                if isinstance(data, dict):
                    responses.append(data)
        except (OSError, TimeoutError, json.JSONDecodeError):
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return responses

    def ingest_live_packet(self, *, meta: Mapping[str, Any], packet: Any) -> list[dict[str, Any]]:
        payload = {
            "device_id": meta["id"],
            "seq": int(getattr(packet, "seq", 1)),
            "cmd": int(getattr(packet, "cmd", 1)),
            "reply": bool(getattr(packet, "reply", True)),
            "err": bool(getattr(packet, "err", False)),
            "rsvd": bool(getattr(packet, "rsvd", False)),
            "data": list(getattr(packet, "data", [0, 0, 0, 0, 0, 0])),
            "packet_timestamp": getattr(packet, "timestamp", None),
            "source": "gateway_live_bus",
        }
        return self.request(
            "ingest_mock_telemetry",
            payload=payload,
            expected_responses=2,
        )

    def gateway_hardware_status(self, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        return self.request(
            "gateway_hardware_status",
            payload=payload,
            expected_responses=1,
        )