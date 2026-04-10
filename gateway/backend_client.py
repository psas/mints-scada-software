# gateway/backend_client.py

"""Persistent gateway-side IPC client for backend JSONL requests.

This module provides the gateway's long-lived Unix-socket client for talking to
the backend service. It handles connection reuse, one retry after transport or
decode failures, live telemetry forwarding, hardware-status publication, and
the paired operator-action/command-request forwarding used by abort flows.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from pathlib import Path
from typing import Any, BinaryIO, Mapping

log = logging.getLogger(__name__)


class BackendIPCClient:
    """Maintain a persistent JSONL socket connection from gateway to backend.

    The client reuses a Unix domain socket connection when possible, serializes
    requests as newline-delimited JSON objects, and closes/reconnects the
    transport when a request fails. Higher-level helpers wrap the backend IPC
    contract used by gateway service code.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        socket_path: Path | None = None,
        timeout_s: float = 1.0,
    ) -> None:
        """Initialize the backend IPC client.

        Args:
            project_root: Project root used to resolve the default backend
                socket path.
            socket_path: Explicit backend Unix socket path. Defaults to
                ``<project_root>/.backend_service.sock``.
            timeout_s: Socket timeout in seconds for connect and I/O.
        """
        self.project_root = Path(project_root).expanduser().resolve()
        if socket_path is None:
            socket_path = self.project_root / ".backend_service.sock"
        self.socket_path = Path(socket_path).expanduser().resolve()
        self.timeout_s = float(timeout_s)
        self._lock = threading.RLock()
        self._conn: socket.socket | None = None
        self._reader: BinaryIO | None = None
        self._writer: BinaryIO | None = None

    def close(self) -> None:
        """Close the current backend connection and file wrappers."""
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        """Close and clear the current socket, reader, and writer state.

        This method expects the caller to already hold ``self._lock``.
        Individual close errors are suppressed so cleanup can continue.
        """
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
        """Ensure the backend socket connection is open.

        This method reuses an existing connection when all transport members are
        present. Otherwise it attempts to connect to the backend Unix socket and
        creates binary reader/writer wrappers.

        Returns:
            True when a usable connection is available. False when the backend
            socket path does not exist yet.

        Raises:
            OSError: If socket creation or connection setup fails.
        """
        if (
            self._conn is not None
            and self._reader is not None
            and self._writer is not None
        ):
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
        """Read one JSON-object response line from the backend connection.

        Returns:
            The decoded backend response object.

        Raises:
            ConnectionError: If the reader is missing or the peer closed the
                connection.
            json.JSONDecodeError: If the received line is not valid JSON.
            ValueError: If the decoded JSON value is not an object.
        """
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
        """Send one backend IPC request and collect the expected responses.

        Requests are encoded as canonical JSONL messages with ``type`` and
        ``payload`` fields. On socket, timeout, decode, or response-shape
        failures, the client logs a warning, closes the transport, and retries
        once from a fresh connection.

        Args:
            message_type: Backend IPC message type to send.
            payload: Payload mapping for the request body.
            expected_responses: Number of response objects to read before
                returning successfully.

        Returns:
            A list of decoded backend response objects. Returns an empty list
            when the backend socket is unavailable or both attempts fail.
        """
        request_bytes = (
            json.dumps(
                {
                    "type": message_type,
                    "payload": dict(payload or {}),
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )

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
                except (
                    OSError,
                    TimeoutError,
                    ConnectionError,
                    json.JSONDecodeError,
                    ValueError,
                ) as exc:
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
        """Forward one live bus packet into the backend ingest path.

        The payload is normalized into the backend's ``ingest_live_telemetry``
        request shape using gateway-owned packet metadata and basic packet
        fields. When provided, the raw event mirror is forwarded alongside the
        normalized packet fields.

        Args:
            meta: Device metadata mapping. The backend request uses ``meta["id"]``
                as the device identifier.
            packet: Live packet object with ``seq``, ``cmd``, ``reply``, ``err``,
                ``rsvd``, ``data``, and optional ``timestamp`` attributes.
            raw_event: Optional first-order raw event payload to include with the
                ingest request.

        Returns:
            The backend responses returned for ``ingest_live_telemetry``. The
            gateway expects two response messages for this request path.
        """
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
            "ingest_live_telemetry", payload=payload, expected_responses=2
        )

    def gateway_hardware_status(
        self, payload: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        """Publish a gateway hardware-status update to the backend.

        Args:
            payload: Gateway hardware-status payload already shaped for the
                backend IPC contract.

        Returns:
            The backend responses returned for ``gateway_hardware_status``.
        """
        return self.request(
            "gateway_hardware_status", payload=payload, expected_responses=1
        )

    def forward_abort_to_backend(
        self,
        *,
        operator_action_payload: Mapping[str, Any],
        command_payload: Mapping[str, Any],
    ) -> tuple[bool, str | None]:
        """Forward the canonical abort pair to the backend and validate acceptance.

        The gateway records the operator action first and then sends the abort
        command request. Success requires both the expected
        ``operator_action_recorded`` response and a successful ``command_result``.

        Args:
            operator_action_payload: Operator-action payload to send to the
                backend.
            command_payload: Abort command-request payload to send to the
                backend.

        Returns:
            A ``(success, error_message)`` tuple. ``error_message`` is None when
            both backend responses match the accepted abort path.
        """
        operator_responses = self.request(
            "operator_action",
            payload=operator_action_payload,
            expected_responses=1,
        )
        command_responses = self.request(
            "command_request",
            payload=command_payload,
            expected_responses=1,
        )
        if not operator_responses or not command_responses:
            return False, "gateway abort forward returned no backend response"

        operator_type = operator_responses[0].get("type")
        command_type = command_responses[0].get("type")
        command_payload_body = command_responses[0].get("payload", {})
        if (
            operator_type == "operator_action_recorded"
            and command_type == "command_result"
            and isinstance(command_payload_body, dict)
            and bool(command_payload_body.get("success"))
        ):
            return True, None

        return False, (
            f"gateway abort forward was not accepted by backend "
            f"(operator_type={operator_type!r}, command_type={command_type!r})"
        )

    def forward_clear_abort_latch_to_backend(
        self,
        *,
        operator_action_payload: Mapping[str, Any],
        command_payload: Mapping[str, Any],
    ) -> tuple[bool, str | None]:
        """Forward the clear-abort-latch pair to the backend and validate acceptance.

        The gateway records the operator action first and then sends the clear
        abort latch command request. Success requires both the expected
        ``operator_action_recorded`` response and a successful ``command_result``.

        Args:
            operator_action_payload: Operator-action payload to send to the
                backend.
            command_payload: Clear-abort-latch command-request payload to send
                to the backend.

        Returns:
            A ``(success, error_message)`` tuple. ``error_message`` is None when
            both backend responses match the accepted clear-abort-latch path.
        """
        operator_responses = self.request(
            "operator_action",
            payload=operator_action_payload,
            expected_responses=1,
        )
        command_responses = self.request(
            "command_request",
            payload=command_payload,
            expected_responses=1,
        )
        if not operator_responses or not command_responses:
            return False, "clear abort latch forward returned no backend response"

        operator_type = operator_responses[0].get("type")
        command_type = command_responses[0].get("type")
        command_payload_body = command_responses[0].get("payload", {})
        if (
            operator_type == "operator_action_recorded"
            and command_type == "command_result"
            and isinstance(command_payload_body, dict)
            and bool(command_payload_body.get("success"))
        ):
            return True, None

        return False, (
            f"clear abort latch forward was not accepted by backend "
            f"(operator_type={operator_type!r}, command_type={command_type!r})"
        )
