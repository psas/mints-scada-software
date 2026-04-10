# backend/gateway_client.py

"""Persistent backend-to-gateway IPC client.

This module provides the backend-side Unix socket client used to talk to the
gateway service. It keeps a reusable request/response connection open across
multiple calls and exposes small helpers for the gateway commands used by the
backend runtime.
"""

from __future__ import annotations

import logging
import socket
import threading
from pathlib import Path
from typing import Any, BinaryIO

from gateway.ipc_models import GatewayIPCMessage, decode_message, encode_message

log = logging.getLogger(__name__)


class GatewayClient:
    """Own a persistent backend-to-gateway IPC session.

    Requests use a synchronous request/response pattern over a reusable Unix
    domain socket connection. The client keeps buffered reader and writer file
    objects for line-delimited message exchange and retries once after closing a
    failed connection.
    """

    def __init__(
        self,
        *,
        project_root: str | Path | None = None,
        socket_path: str | Path | None = None,
        timeout_s: float = 1.0,
    ) -> None:
        """Initialize the gateway IPC client.

        Args:
            project_root: Project root used to derive the default gateway socket
                path when ``socket_path`` is not provided.
            socket_path: Explicit Unix domain socket path for the gateway
                service.
            timeout_s: Socket timeout applied to the underlying Unix socket.
        """
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

        self._lock = threading.RLock()
        self._conn: socket.socket | None = None
        self._reader: BinaryIO | None = None
        self._writer: BinaryIO | None = None

    def close(self) -> None:
        """Close the current IPC connection and buffered file objects.

        Returns:
            None.
        """
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        """Close and clear the current connection state under the client lock.

        Returns:
            None.
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
        """Ensure a live gateway connection exists under the client lock.

        Returns:
            True when the client is connected and has active buffered reader and
            writer streams. False when the gateway socket path does not exist.

        Raises:
            OSError: Raised when the Unix socket cannot be connected or wrapped
                after the socket path is found.
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

    def _read_message_locked(self) -> GatewayIPCMessage:
        """Read and decode one line-delimited IPC message under the client lock.

        Returns:
            The decoded gateway IPC message.

        Raises:
            ConnectionError: Raised when the client has no reader or the peer
                closes the connection before a full message is read.
        """
        if self._reader is None:
            raise ConnectionError("Gateway IPC reader is not connected")

        line = self._reader.readline()
        if not line:
            raise ConnectionError("Gateway IPC connection closed by peer")

        return decode_message(line.rstrip(b"\n"))

    def request(
        self,
        message_type: str,
        *,
        payload: dict | None = None,
        expected_responses: int = 1,
    ) -> list[GatewayIPCMessage]:
        """Send one gateway request and read the expected response messages.

        The client reuses its existing connection when possible. On socket,
        timeout, or connection failures, it closes the current session and
        retries once with a fresh connection.

        Args:
            message_type: Gateway IPC message type to send.
            payload: JSON-serializable payload dictionary for the request.
            expected_responses: Number of response messages to read before
                returning.

        Returns:
            A list of decoded gateway IPC responses. Returns an empty list when
            the gateway socket is unavailable or both request attempts fail.
        """
        request = GatewayIPCMessage(type=message_type, payload=payload or {})

        with self._lock:
            for attempt in range(2):
                try:
                    if not self._connect_locked():
                        return []

                    assert self._writer is not None

                    self._writer.write(encode_message(request))
                    self._writer.write(b"\n")
                    self._writer.flush()

                    responses: list[GatewayIPCMessage] = []
                    for _ in range(expected_responses):
                        responses.append(self._read_message_locked())
                    return responses
                except (OSError, TimeoutError, ConnectionError) as exc:
                    log.warning(
                        "Gateway IPC request failed (type=%s, attempt=%s/%s): %s",
                        message_type,
                        attempt + 1,
                        2,
                        exc,
                    )
                    self._close_locked()
                    if attempt == 1:
                        return []

        return []

    def hello(
        self,
        *,
        service_name: str,
        backend_socket_path: str,
    ) -> list[GatewayIPCMessage]:
        """Send the gateway hello handshake for this backend service.

        Args:
            service_name: Backend service name presented to the gateway.
            backend_socket_path: Backend IPC socket path the gateway should use
                for callback or peer communication.

        Returns:
            The two expected handshake response messages from the gateway.
        """
        return self.request(
            "hello",
            payload={
                "service_name": service_name,
                "backend_socket_path": backend_socket_path,
            },
            expected_responses=2,
        )

    def ping(self) -> list[GatewayIPCMessage]:
        """Send a gateway ping request.

        Returns:
            The single ping response message from the gateway.
        """
        return self.request("ping", expected_responses=1)

    def status_request(self) -> list[GatewayIPCMessage]:
        """Request the current gateway runtime status.

        Returns:
            The single status response message from the gateway.
        """
        return self.request("status_request", expected_responses=1)

    def initialize_live_hardware(self) -> list[GatewayIPCMessage]:
        """Ask the gateway to initialize live hardware access.

        Returns:
            The single response message for the initialization request.
        """
        return self.request("initialize_live_hardware", expected_responses=1)

    def shutdown_live_hardware(self) -> list[GatewayIPCMessage]:
        """Ask the gateway to shut down live hardware access.

        Returns:
            The single response message for the shutdown request.
        """
        return self.request("shutdown_live_hardware", expected_responses=1)

    def send_packet(
        self,
        *,
        device_id: str,
        packet: Any,
    ) -> list[GatewayIPCMessage]:
        """Send one outbound packet request through the gateway.

        The packet is normalized into the gateway IPC payload shape using the
        packet object's ``id``, ``seq``, ``cmd``, flag fields, and ``data``.

        Args:
            device_id: Canonical device identifier associated with the outbound
                packet.
            packet: Packet-like object with the fields consumed by the gateway
                send-packet IPC contract.

        Returns:
            The single response message for the send request.

        Raises:
            ValueError: Raised when the packet does not expose an ``id`` field.
        """
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
        """Tell the gateway to open a new run-scoped raw history session.

        Args:
            run_id: Canonical run identifier.
            test_name: User-facing test name for the run metadata.
            mode: Run mode recorded in the gateway history metadata.
            operator: Operator name for run metadata.
            profile_name: Selected profile name for the run.
            notes: Freeform run notes.
            software_git_commit: Git commit recorded for the software build.
            software_branch: Source branch recorded for the software build.
            device_map_version: Device-map version string for run metadata.
            svg_version: SCADA or SVG version string for run metadata.
            bus_config: Bus configuration metadata forwarded to the gateway.
            clock_info: Clock metadata forwarded to the gateway.
            extra_metadata: Additional run metadata forwarded to the gateway.

        Returns:
            The single response message for the start-run request.
        """
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
        """Tell the gateway to finish the current run-scoped raw history session.

        Args:
            run_id: Canonical run identifier to close.
            reason: Finish reason recorded with the run close request.

        Returns:
            The single response message for the finish-run request.
        """
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
        """Forward a first-order raw event to the gateway raw history writer.

        Args:
            stream_name: Raw stream name to append to.
            event: Raw event payload to record.

        Returns:
            The single response message for the raw-event record request.
        """
        return self.request(
            "record_raw_event",
            payload={
                "stream_name": stream_name,
                "event": dict(event),
            },
            expected_responses=1,
        )
