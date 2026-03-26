from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(slots=True)
class GatewayIPCMessage:
    """A JSON-lines IPC message for backend/gateway communication."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)


def encode_message(message: GatewayIPCMessage) -> bytes:
    """Encode a gateway IPC message to a single JSON line."""
    return json.dumps(
        {
            "type": message.type,
            "payload": dict(message.payload),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def decode_message(raw: bytes | str) -> GatewayIPCMessage:
    """Decode a gateway IPC JSON line into a message object."""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8")
    else:
        text = raw

    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("IPC message must decode to a JSON object")

    message_type = data.get("type")
    if not isinstance(message_type, str) or not message_type:
        raise ValueError("IPC message requires a non-empty string 'type'")

    payload = data.get("payload", {})
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("IPC message 'payload' must be a JSON object")

    return GatewayIPCMessage(type=message_type, payload=payload)


def hello_ack_message(
    *,
    service_name: str,
    gateway_started_at: str,
    connected_clients: int,
    supported_messages: list[str],
) -> GatewayIPCMessage:
    """Build a hello acknowledgement message."""
    return GatewayIPCMessage(
        type="hello_ack",
        payload={
            "service_name": service_name,
            "gateway_started_at": gateway_started_at,
            "connected_clients": connected_clients,
            "supported_messages": list(supported_messages),
        },
    )


def pong_message() -> GatewayIPCMessage:
    """Build a pong response."""
    return GatewayIPCMessage(type="pong", payload={})


def gateway_status_message(
    *,
    service_name: str,
    gateway_started_at: str,
    socket_path: str,
    connected_clients: int,
    supported_messages: list[str],
) -> GatewayIPCMessage:
    """Build a gateway status response."""
    return GatewayIPCMessage(
        type="gateway_status",
        payload={
            "service_name": service_name,
            "gateway_started_at": gateway_started_at,
            "socket_path": socket_path,
            "connected_clients": connected_clients,
            "supported_messages": list(supported_messages),
        },
    )


def error_message(
    *,
    code: str,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> GatewayIPCMessage:
    """Build an IPC error response."""
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if details:
        payload["details"] = dict(details)
    return GatewayIPCMessage(type="error", payload=payload)