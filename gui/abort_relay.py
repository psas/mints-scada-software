# gui/abort_relay.py

"""Local relay process for abort and clear-abort-latch gateway requests.

This module exposes a small Unix-domain-socket server that accepts GUI-side
abort relay messages, enriches them with relay session metadata, forwards them
to the gateway service, and returns the gateway result to the caller.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.script_runtime.abort_flow_contract import (
    CLEAR_ABORT_LATCH_RELAY_MESSAGE_TYPE,
    build_clear_abort_latch_command_payload,
    build_clear_abort_latch_operator_action_payload,
)
from scripts.script_runtime.script_contract import (
    ABORT_RELAY_MESSAGE_TYPE,
    build_abort_command_payload,
    build_abort_operator_action_payload,
)

log = logging.getLogger(__name__)


def _project_root() -> Path:
    """Return the repository root used by the relay process.

    Returns:
        The project root directory derived from this module location.
    """
    return PROJECT_ROOT


def isoformat_z() -> str:
    """Return the current UTC time in millisecond ISO-8601 ``Z`` format.

    Returns:
        A UTC timestamp formatted as ``YYYY-MM-DDTHH:MM:SS.mmmZ``.
    """
    return (
        time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        + f".{int((time.time() % 1) * 1000):03d}Z"
    )


def _configure_logging() -> None:
    """Configure file and stream logging for the relay process.

    The relay writes into the repository ``log/debug.log`` file and also emits
    the same records through the standard stream handler.

    Returns:
        None.
    """
    formatstr = "%(asctime)s [%(name)-16.16s] [%(levelname)-5.5s] %(message)s"
    log_dir = _project_root() / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG,
        format=formatstr,
        handlers=[
            logging.FileHandler(log_dir / "debug.log"),
            logging.StreamHandler(),
        ],
    )


def _json_line(payload: Mapping[str, Any]) -> bytes:
    """Encode a mapping as one UTF-8 JSONL record.

    Args:
        payload: Message payload to encode.

    Returns:
        The JSON-serialized payload followed by a newline as UTF-8 bytes.
    """
    return (
        json.dumps(dict(payload), ensure_ascii=False, sort_keys=False) + "\n"
    ).encode("utf-8")


def send_abort_relay_message(
    *,
    relay_socket: str | Path,
    message_type: str,
    payload: Mapping[str, Any] | None = None,
    timeout_s: float = 3.0,
) -> dict[str, Any]:
    """Send a single request to a running abort relay and wait for one reply.

    Args:
        relay_socket: Unix-domain socket path exposed by the relay server.
        message_type: Relay message type to send.
        payload: Optional request payload object.
        timeout_s: Socket and overall reply timeout in seconds.

    Returns:
        The first JSON object returned by the relay.

    Raises:
        TimeoutError: If the relay does not return a reply before the deadline.
        OSError: If the client cannot connect to the relay socket.
        json.JSONDecodeError: If the relay returns malformed JSON.
    """
    socket_path = Path(relay_socket).expanduser().resolve()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout_s)
        sock.connect(str(socket_path))
        sock.sendall(_json_line({"type": message_type, "payload": dict(payload or {})}))
        buffer = ""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                decoded = json.loads(line)
                if isinstance(decoded, dict):
                    return decoded
    raise TimeoutError(f"AbortRelay did not reply to {message_type!r} in time")


def send_abort_request(
    *,
    relay_socket: str | Path,
    source_window_role: str | None = None,
    source_window_kind: str | None = None,
    source_mode: str | None = None,
    command_payload: Mapping[str, Any] | None = None,
    operator_action: Mapping[str, Any] | None = None,
    timeout_s: float = 4.0,
) -> dict[str, Any]:
    """Send a canonical abort relay request to a running relay server.

    Args:
        relay_socket: Unix-domain socket path exposed by the relay server.
        source_window_role: Optional logical role of the requesting GUI window.
        source_window_kind: Optional GUI window kind for audit metadata.
        source_mode: Optional mode string such as live or playback.
        command_payload: Optional command payload overrides forwarded to the relay.
        operator_action: Optional operator-action payload fields forwarded to the relay.
        timeout_s: Socket and overall reply timeout in seconds.

    Returns:
        The relay response dictionary for the abort request.
    """
    payload: dict[str, Any] = {}
    if source_window_role:
        payload["source_window_role"] = source_window_role
    if source_window_kind:
        payload["source_window_kind"] = source_window_kind
    if source_mode:
        payload["source_mode"] = source_mode
    if command_payload:
        payload["command_payload"] = dict(command_payload)
    if operator_action:
        payload["operator_action"] = dict(operator_action)
    return send_abort_relay_message(
        relay_socket=relay_socket,
        message_type=ABORT_RELAY_MESSAGE_TYPE,
        payload=payload,
        timeout_s=timeout_s,
    )


def send_clear_abort_latch_request(
    *,
    relay_socket: str | Path,
    source_window_role: str | None = None,
    source_window_kind: str | None = None,
    source_mode: str | None = None,
    command_payload: Mapping[str, Any] | None = None,
    operator_action: Mapping[str, Any] | None = None,
    timeout_s: float = 4.0,
) -> dict[str, Any]:
    """Send a clear-abort-latch relay request to a running relay server.

    Args:
        relay_socket: Unix-domain socket path exposed by the relay server.
        source_window_role: Optional logical role of the requesting GUI window.
        source_window_kind: Optional GUI window kind for audit metadata.
        source_mode: Optional mode string such as live or playback.
        command_payload: Optional command payload overrides forwarded to the relay.
        operator_action: Optional operator-action payload fields forwarded to the relay.
        timeout_s: Socket and overall reply timeout in seconds.

    Returns:
        The relay response dictionary for the clear-abort-latch request.
    """
    payload: dict[str, Any] = {}
    if source_window_role:
        payload["source_window_role"] = source_window_role
    if source_window_kind:
        payload["source_window_kind"] = source_window_kind
    if source_mode:
        payload["source_mode"] = source_mode
    if command_payload:
        payload["command_payload"] = dict(command_payload)
    if operator_action:
        payload["operator_action"] = dict(operator_action)
    return send_abort_relay_message(
        relay_socket=relay_socket,
        message_type=CLEAR_ABORT_LATCH_RELAY_MESSAGE_TYPE,
        payload=payload,
        timeout_s=timeout_s,
    )


class AbortRelayServer:
    """Serve local abort relay requests and proxy them to the gateway.

    The relay listens on a Unix-domain socket, accepts GUI-originated abort and
    clear-abort-latch requests, adds relay session metadata, builds canonical
    operator-action and command payloads, and forwards the request to the live
    gateway socket.
    """

    def __init__(self, *, relay_socket: str | Path, gateway_socket: str | Path) -> None:
        """Initialize relay socket paths and session state.

        Args:
            relay_socket: Unix-domain socket path exposed to local relay clients.
            gateway_socket: Unix-domain socket path for the gateway service.
        """
        self.relay_socket = Path(relay_socket).expanduser().resolve()
        self.gateway_socket = Path(gateway_socket).expanduser().resolve()
        self.session_id = uuid4().hex
        self._stop_event = threading.Event()
        self._server_socket: socket.socket | None = None

    def serve_forever(self) -> None:
        """Start the relay server loop and handle clients until stopped.

        This method binds the relay socket, accepts client connections, and
        dispatches each connection to a daemon thread that processes JSONL
        requests until the server is asked to stop.

        Returns:
            None.
        """
        self.relay_socket.parent.mkdir(parents=True, exist_ok=True)
        if self.relay_socket.exists():
            self.relay_socket.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_socket = server
        server.bind(str(self.relay_socket))
        server.listen(16)
        server.settimeout(0.5)
        log.info(
            "AbortRelay listening on %s (gateway=%s)",
            self.relay_socket,
            self.gateway_socket,
        )
        try:
            while not self._stop_event.is_set():
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop_event.is_set():
                        break
                    raise
                thread = threading.Thread(
                    target=self._handle_client, args=(conn,), daemon=True
                )
                thread.start()
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the relay server and remove the relay socket path.

        Returns:
            None.
        """
        self._stop_event.set()
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None
        try:
            if self.relay_socket.exists():
                self.relay_socket.unlink()
        except Exception:
            pass

    def _handle_client(self, conn: socket.socket) -> None:
        """Process JSONL requests from one connected relay client.

        Args:
            conn: Accepted Unix-domain socket connection.

        Returns:
            None.
        """
        with conn:
            conn.settimeout(2.0)
            buffer = ""
            while not self._stop_event.is_set():
                try:
                    chunk = conn.recv(65536)
                except socket.timeout:
                    break
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        request = json.loads(line)
                        if not isinstance(request, dict):
                            raise ValueError("request must decode to an object")
                        response = self._process_request(request)
                    except Exception as exc:
                        response = {
                            "type": "error",
                            "payload": {
                                "ok": False,
                                "error": str(exc),
                            },
                        }
                    conn.sendall(_json_line(response))

    def _process_request(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Route one decoded relay request to the appropriate handler.

        Args:
            request: Decoded JSON request object containing ``type`` and optional
                ``payload`` fields.

        Returns:
            The response object that should be written back to the client.

        Raises:
            ValueError: If the payload is not an object or the message type is
                unsupported.
        """
        message_type = request.get("type")
        payload = request.get("payload", {})
        if payload is None:
            payload = {}
        if not isinstance(payload, Mapping):
            raise ValueError("AbortRelay request payload must be an object")

        if message_type == "ping":
            return {
                "type": "pong",
                "payload": {
                    "ok": True,
                    "relay_name": "gui-abort-relay",
                    "session_id": self.session_id,
                    "pid": os.getpid(),
                    "relay_socket": str(self.relay_socket),
                    "gateway_socket": str(self.gateway_socket),
                    "wall_time": isoformat_z(),
                },
            }
        if message_type == ABORT_RELAY_MESSAGE_TYPE:
            return self._handle_abort_request(payload)
        if message_type == CLEAR_ABORT_LATCH_RELAY_MESSAGE_TYPE:
            return self._handle_clear_abort_latch_request(payload)
        raise ValueError(f"Unsupported AbortRelay message type: {message_type!r}")

    def _handle_abort_request(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Build and forward one abort request through the gateway.

        Args:
            payload: Relay request payload from a local client.

        Returns:
            A relay ``abort_result`` response containing the generated relay
            request identifiers, the raw gateway response, and an ``ok`` flag.
        """
        relay_request_id = uuid4().hex
        source_window_role = self._get_optional_string(payload, "source_window_role")
        source_window_kind = self._get_optional_string(payload, "source_window_kind")
        source_mode = self._get_optional_string(payload, "source_mode")
        requested_at = isoformat_z()
        operator_action_extra = (
            self._get_optional_mapping(payload, "operator_action") or {}
        )
        command_payload_override = (
            self._get_optional_mapping(payload, "command_payload") or {}
        )

        operator_action_payload = build_abort_operator_action_payload(
            relay_request_id=relay_request_id,
            relay_session_id=self.session_id,
            requested_at=requested_at,
            source_window_role=source_window_role,
            source_window_kind=source_window_kind,
            source_mode=source_mode,
            extra=operator_action_extra,
        )
        command_payload = build_abort_command_payload(
            relay_request_id=relay_request_id,
            relay_session_id=self.session_id,
            source_window_role=source_window_role,
            source_window_kind=source_window_kind,
            source_mode=source_mode,
            extra=command_payload_override,
        )

        gateway_response = self._gateway_exchange(
            message_type=ABORT_RELAY_MESSAGE_TYPE,
            payload={
                "relay_request_id": relay_request_id,
                "relay_session_id": self.session_id,
                "requested_via": "abort_relay",
                "requested_at": requested_at,
                "source_window_role": source_window_role,
                "source_window_kind": source_window_kind,
                "source_mode": source_mode,
                "operator_action": operator_action_payload,
                "command_payload": command_payload,
            },
            expected_response_types=("abort_result", "error"),
        )
        payload_body = (
            gateway_response.get("payload", {})
            if isinstance(gateway_response, dict)
            else {}
        )
        ok = (
            gateway_response.get("type") == "abort_result"
            and isinstance(payload_body, Mapping)
            and bool(payload_body.get("ok"))
        )
        return {
            "type": "abort_result",
            "payload": {
                "ok": ok,
                "relay_request_id": relay_request_id,
                "relay_session_id": self.session_id,
                "gateway_response": gateway_response,
                "wall_time": isoformat_z(),
            },
        }

    def _handle_clear_abort_latch_request(
        self, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Build and forward one clear-abort-latch request through the gateway.

        Args:
            payload: Relay request payload from a local client.

        Returns:
            A relay ``clear_abort_latch_result`` response containing the
            generated relay request identifiers, the raw gateway response, and
            an ``ok`` flag.
        """
        relay_request_id = uuid4().hex
        source_window_role = self._get_optional_string(payload, "source_window_role")
        source_window_kind = self._get_optional_string(payload, "source_window_kind")
        source_mode = self._get_optional_string(payload, "source_mode")
        requested_at = isoformat_z()
        operator_action_extra = (
            self._get_optional_mapping(payload, "operator_action") or {}
        )
        command_payload_override = (
            self._get_optional_mapping(payload, "command_payload") or {}
        )

        operator_action_payload = build_clear_abort_latch_operator_action_payload(
            relay_request_id=relay_request_id,
            relay_session_id=self.session_id,
            requested_at=requested_at,
            source_window_role=source_window_role,
            source_window_kind=source_window_kind,
            source_mode=source_mode,
            extra=operator_action_extra,
        )
        command_payload = build_clear_abort_latch_command_payload(
            relay_request_id=relay_request_id,
            relay_session_id=self.session_id,
            source_window_role=source_window_role,
            source_window_kind=source_window_kind,
            source_mode=source_mode,
            extra=command_payload_override,
        )

        gateway_response = self._gateway_exchange(
            message_type=CLEAR_ABORT_LATCH_RELAY_MESSAGE_TYPE,
            payload={
                "relay_request_id": relay_request_id,
                "relay_session_id": self.session_id,
                "requested_via": "abort_relay",
                "requested_at": requested_at,
                "source_window_role": source_window_role,
                "source_window_kind": source_window_kind,
                "source_mode": source_mode,
                "operator_action": operator_action_payload,
                "command_payload": command_payload,
            },
            expected_response_types=("clear_abort_latch_result", "error"),
        )
        payload_body = (
            gateway_response.get("payload", {})
            if isinstance(gateway_response, dict)
            else {}
        )
        ok = (
            gateway_response.get("type") == "clear_abort_latch_result"
            and isinstance(payload_body, Mapping)
            and bool(payload_body.get("ok"))
        )
        return {
            "type": "clear_abort_latch_result",
            "payload": {
                "ok": ok,
                "relay_request_id": relay_request_id,
                "relay_session_id": self.session_id,
                "gateway_response": gateway_response,
                "wall_time": isoformat_z(),
            },
        }

    def _gateway_exchange(
        self,
        *,
        message_type: str,
        payload: Mapping[str, Any],
        expected_response_types: tuple[str, ...],
        timeout_s: float = 3.0,
    ) -> dict[str, Any]:
        """Send one request to the gateway and wait for an allowed response type.

        The relay opens a fresh gateway connection for each forwarded request,
        sends a ``hello`` handshake that identifies this process as the
        abort-relay client, then sends the actual relay payload.

        Args:
            message_type: Gateway message type to send after the handshake.
            payload: Gateway payload object to forward.
            expected_response_types: Acceptable gateway response message types.
            timeout_s: Socket and overall reply timeout in seconds.

        Returns:
            The first decoded gateway response whose ``type`` matches one of
            ``expected_response_types``.

        Raises:
            TimeoutError: If the gateway does not return an expected response
                before the deadline.
            OSError: If the relay cannot connect to the gateway socket.
            json.JSONDecodeError: If the gateway returns malformed JSON.
        """
        hello_payload = {
            "client_name": "abort-relay",
            "logical_client_id": "gui:abort-relay",
            "window_role": "abort_relay",
            "session_id": self.session_id,
            "mode": "live",
            "window_kind": "abort_relay",
            "pid": os.getpid(),
        }
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout_s)
            sock.connect(str(self.gateway_socket))
            sock.sendall(_json_line({"type": "hello", "payload": hello_payload}))
            sock.sendall(_json_line({"type": message_type, "payload": dict(payload)}))
            buffer = ""
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    decoded = json.loads(line)
                    if not isinstance(decoded, dict):
                        continue
                    decoded_type = decoded.get("type")
                    if decoded_type == "hello_ack":
                        continue
                    if decoded_type in expected_response_types:
                        return decoded
        raise TimeoutError(
            f"AbortRelay timed out waiting for gateway response types {expected_response_types!r}"
        )

    def _get_optional_mapping(
        self, payload: Mapping[str, Any], key: str
    ) -> dict[str, Any] | None:
        """Return an optional nested object from a relay payload.

        Args:
            payload: Relay payload to inspect.
            key: Field name to read.

        Returns:
            A shallow ``dict`` copy of the nested mapping, or None when the
            field is absent.

        Raises:
            ValueError: If the field is present but is not an object.
        """
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError(
                f"AbortRelay field {key!r} must be an object when provided"
            )
        return dict(value)

    def _get_optional_string(self, payload: Mapping[str, Any], key: str) -> str | None:
        """Return an optional stripped string from a relay payload.

        Args:
            payload: Relay payload to inspect.
            key: Field name to read.

        Returns:
            The stripped string value, or None when the field is absent or
            contains only whitespace.

        Raises:
            ValueError: If the field is present but is not a string.
        """
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"AbortRelay field {key!r} must be a string when provided")
        stripped = value.strip()
        return stripped or None


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the standalone abort relay process.

    Returns:
        The configured argument parser for relay startup.
    """
    parser = argparse.ArgumentParser(
        description="Run the minTS local AbortRelay process"
    )
    parser.add_argument("--gateway-socket", required=True)
    parser.add_argument("--relay-socket", required=True)
    return parser


def main() -> int:
    """Run the standalone abort relay server process.

    Returns:
        ``0`` when the server exits normally, or ``130`` when interrupted by
        the user.
    """
    _configure_logging()
    parser = _build_arg_parser()
    args = parser.parse_args()
    server = AbortRelayServer(
        relay_socket=args.relay_socket,
        gateway_socket=args.gateway_socket,
    )
    try:
        server.serve_forever()
        return 0
    except KeyboardInterrupt:
        log.info("AbortRelay interrupted; shutting down")
        return 130
    finally:
        server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
