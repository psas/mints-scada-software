from __future__ import annotations

import json
import logging
import socket
import threading
from pathlib import Path
from typing import Any, BinaryIO, Mapping

log = logging.getLogger(__name__)


class BackendIPCClient:
    """Persistent gateway -> backend IPC client.

    This replaces the previous one-shot per-message socket behavior with a
    reusable Unix socket session. Requests remain synchronous request/response,
    but the connection is reused across many requests and buffered line reads
    replace byte-at-a-time reads.
    """

    def __init__(
        self,
        *,
        project_root: str | Path | None = None,
        socket_path: str | Path | None = None,
        timeout_s: float = 1.0,
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

        self._lock = threading.RLock()
        self._conn: socket.socket | None = None
        self._reader: BinaryIO | None = None
        self._writer: BinaryIO | None = None

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        reader = self._reader
        writer = self._writer
        conn = self._conn

        self._reader = None
        self._writer = None
        self._conn = None

        if reader is not None:
            try:
                reader.close()
            except Exception:
                pass

        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass

        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def _connect_locked(self) -> bool:
        if self._conn is not None and self._reader is not None and self._writer is not None:
            return True

        if not self.socket_path.exists():
            return False

        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(self.timeout_s)

        try:
            conn.connect(str(self.socket_path))
            reader = conn.makefile("rb")
            writer = conn.makefile("wb")
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            raise

        self._conn = conn
        self._reader = reader
        self._writer = writer
        return True

    def _read_json_message_locked(self) -> dict[str, Any]:
        if self._reader is None:
            raise ConnectionError("Backend IPC reader is not connected")

        line = self._reader.readline()
        if not line:
            raise ConnectionError("Backend IPC connection closed by peer")

        data = json.loads(line.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Backend IPC response must be a JSON object")
        return data

    def request(
        self,
        message_type: str,
        *,
        payload: Mapping[str, Any] | None = None,
        expected_responses: int = 1,
    ) -> list[dict[str, Any]]:
        request_bytes = json.dumps(
            {
                "type": message_type,
                "payload": dict(payload or {}),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8") + b"\n"

        with self._lock:
            for attempt in range(2):
                try:
                    if not self._connect_locked():
                        return []

                    assert self._writer is not None

                    self._writer.write(request_bytes)
                    self._writer.flush()

                    responses: list[dict[str, Any]] = []
                    for _ in range(expected_responses):
                        responses.append(self._read_json_message_locked())
                    return responses
                except (OSError, TimeoutError, ConnectionError, json.JSONDecodeError, ValueError) as exc:
                    log.warning(
                        "Backend IPC request failed (type=%s, attempt=%s/%s): %s",
                        message_type,
                        attempt + 1,
                        2,
                        exc,
                    )
                    self._close_locked()
                    if attempt == 1:
                        return []

        return []

    def ingest_live_packet(
        self,
        *,
        meta: Mapping[str, Any],
        packet: Any,
        raw_event: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
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
        if raw_event is not None:
            payload["raw_event"] = dict(raw_event)

        return self.request(
            "ingest_live_telemetry",
            payload=payload,
            expected_responses=2,
        )

    def gateway_hardware_status(self, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        return self.request(
            "gateway_hardware_status",
            payload=payload,
            expected_responses=1,
        )