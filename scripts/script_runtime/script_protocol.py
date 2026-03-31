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
    """Plain JSON-serializable protocol envelope used by the script host."""

    type: str
    payload: dict[str, Any]
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
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
    """Build a protocol message dictionary."""
    return ScriptHostMessage(
        type=str(message_type),
        payload=dict(payload or {}),
        request_id=request_id,
    ).to_dict()



def encode_json_line(payload: Mapping[str, Any]) -> bytes:
    """Encode a single protocol payload as a JSONL line."""
    return (json.dumps(dict(payload), ensure_ascii=False, sort_keys=False) + "\n").encode("utf-8")



def decode_json_line(line: str) -> dict[str, Any]:
    """Decode a single JSONL line and validate the envelope shape."""
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
