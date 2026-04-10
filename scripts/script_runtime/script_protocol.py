# scripts/script_runtime/script_protocol.py

"""JSONL protocol helpers for subprocess legacy script host messaging.

This module defines the lightweight message envelope shared between the script
runner side and the isolated stdio-based script host. It centralizes protocol
message names, supported inbound request types, envelope construction, and
JSONL encoding/decoding with basic shape validation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

SCRIPT_HOST_PROTOCOL_VERSION = 1

SCRIPT_HOST_MESSAGE_HOST_READY = "host_ready"
SCRIPT_HOST_MESSAGE_PING = "ping"
SCRIPT_HOST_MESSAGE_PONG = "pong"
SCRIPT_HOST_MESSAGE_SHUTDOWN = "shutdown"
SCRIPT_HOST_MESSAGE_SHUTDOWN_ACK = "shutdown_ack"
SCRIPT_HOST_MESSAGE_ERROR = "error"
SCRIPT_HOST_MESSAGE_EXECUTE_LEGACY_SCRIPT = "execute_legacy_script"
SCRIPT_HOST_MESSAGE_EXECUTE_STARTED = "execute_started"
SCRIPT_HOST_MESSAGE_SCRIPT_OUTPUT = "script_output"
SCRIPT_HOST_MESSAGE_COMMAND_REQUEST = "command_request"
SCRIPT_HOST_MESSAGE_ABORT_REQUEST = "abort_request"
SCRIPT_HOST_MESSAGE_SCRIPT_EXIT = "script_exit"

SCRIPT_HOST_SUPPORTED_REQUEST_TYPES: tuple[str, ...] = (
    SCRIPT_HOST_MESSAGE_PING,
    SCRIPT_HOST_MESSAGE_SHUTDOWN,
    SCRIPT_HOST_MESSAGE_EXECUTE_LEGACY_SCRIPT,
)


@dataclass(frozen=True)
class ScriptHostMessage:
    """Represent one script-host protocol envelope.

    The envelope is intentionally plain and JSON-serializable so it can cross
    the stdio boundary between the backend-owned script runner and the isolated
    legacy script host.

    Attributes:
        type: Protocol message type.
        payload: Message payload object carried by the envelope.
        request_id: Optional request identifier used to correlate request and
            response messages.
    """

    type: str
    payload: dict[str, Any]
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Build the JSON-serializable dictionary form of the envelope.

        Returns:
            A protocol message dictionary containing the current protocol
            version, message type, payload copy, and optional request ID.
        """
        message = {
            "protocol_version": SCRIPT_HOST_PROTOCOL_VERSION,
            "type": self.type,
            "payload": dict(self.payload),
        }
        if self.request_id:
            message["request_id"] = self.request_id
        return message


def build_message(
    message_type: str,
    payload: Mapping[str, Any] | None = None,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build a protocol message dictionary from envelope fields.

    Args:
        message_type: Protocol message type to encode into the envelope.
        payload: Payload mapping to copy into the message. Defaults to an empty
            object when omitted.
        request_id: Optional request identifier to include in the envelope.

    Returns:
        A JSON-serializable protocol message dictionary.
    """
    return ScriptHostMessage(
        type=str(message_type),
        payload=dict(payload or {}),
        request_id=request_id,
    ).to_dict()


def encode_json_line(payload: Mapping[str, Any]) -> bytes:
    """Encode one protocol message as a UTF-8 JSONL line.

    Args:
        payload: Protocol message mapping to serialize.

    Returns:
        The serialized JSON bytes terminated by a single newline.
    """
    return (
        json.dumps(dict(payload), ensure_ascii=False, sort_keys=False) + "\n"
    ).encode("utf-8")


def decode_json_line(line: str) -> dict[str, Any]:
    """Decode and validate one JSONL protocol message envelope.

    Args:
        line: One JSON object line read from the protocol stream.

    Returns:
        The decoded protocol message dictionary. When the decoded envelope omits
        ``payload`` or sets it to null, the returned dictionary contains an
        empty payload object instead.

    Raises:
        ValueError: The decoded object is not a valid protocol envelope, uses an
            unsupported protocol version, has an empty message type, or has a
            non-object payload.
        json.JSONDecodeError: The input line is not valid JSON.
    """
    decoded = json.loads(line)
    if not isinstance(decoded, dict):
        raise ValueError("Script host protocol message must decode to an object")
    protocol_version = decoded.get("protocol_version")
    if protocol_version != SCRIPT_HOST_PROTOCOL_VERSION:
        raise ValueError(
            f"Unsupported script host protocol version {protocol_version!r}; "
            f"expected {SCRIPT_HOST_PROTOCOL_VERSION!r}"
        )
    message_type = decoded.get("type")
    if not isinstance(message_type, str) or not message_type.strip():
        raise ValueError("Script host protocol message requires a non-empty 'type'")
    payload = decoded.get("payload")
    if payload is None:
        decoded["payload"] = {}
    elif not isinstance(payload, dict):
        raise ValueError("Script host protocol message payload must be an object")
    return decoded
