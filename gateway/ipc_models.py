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
    return json.dumps(
        {
            "type": message.type,
            "payload": dict(message.payload),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def decode_message(raw: bytes | str) -> GatewayIPCMessage:
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
    return GatewayIPCMessage(type="pong", payload={})


def hardware_status_message(
    *,
    connected: bool,
    reconnecting: bool = False,
    status: str | None = None,
    reason: str | None = None,
    sender: str | None = None,
    bitrate: int | None = None,
    registered_ids: list[str] | None = None,
    skipped_ids: list[str] | None = None,
    registered_count: int | None = None,
    skipped_count: int | None = None,
    already_running: bool = False,
    packet_listener_attached: bool | None = None,
    wall_time: str | None = None,
) -> GatewayIPCMessage:
    payload: dict[str, Any] = {
        "connected": bool(connected),
        "reconnecting": bool(reconnecting),
        "already_running": bool(already_running),
        "registered_ids": list(registered_ids or []),
        "skipped_ids": list(skipped_ids or []),
    }
    if status is not None:
        payload["status"] = status
    if reason is not None:
        payload["reason"] = reason
    if sender is not None:
        payload["sender"] = sender
    if bitrate is not None:
        payload["bitrate"] = int(bitrate)
    if registered_count is not None:
        payload["registered_count"] = int(registered_count)
    if skipped_count is not None:
        payload["skipped_count"] = int(skipped_count)
    if packet_listener_attached is not None:
        payload["packet_listener_attached"] = bool(packet_listener_attached)
    if wall_time is not None:
        payload["wall_time"] = wall_time
    return GatewayIPCMessage(type="hardware_status", payload=payload)


def packet_sent_message(
    *,
    device_id: str | None,
    packet_id: int,
    seq: int,
    cmd: int,
    sender: str | None = None,
    bitrate: int | None = None,
) -> GatewayIPCMessage:
    payload: dict[str, Any] = {
        "packet_id": int(packet_id),
        "seq": int(seq),
        "cmd": int(cmd),
    }
    if device_id is not None:
        payload["device_id"] = device_id
    if sender is not None:
        payload["sender"] = sender
    if bitrate is not None:
        payload["bitrate"] = int(bitrate)
    return GatewayIPCMessage(type="packet_sent", payload=payload)


def gateway_status_message(
    *,
    service_name: str,
    gateway_started_at: str,
    socket_path: str,
    connected_clients: int,
    supported_messages: list[str],
    bus_connected: bool,
    sender: str | None,
    bitrate: int | None,
    registered_ids: list[str],
    skipped_ids: list[str],
) -> GatewayIPCMessage:
    return GatewayIPCMessage(
        type="gateway_status",
        payload={
            "service_name": service_name,
            "gateway_started_at": gateway_started_at,
            "socket_path": socket_path,
            "connected_clients": connected_clients,
            "supported_messages": list(supported_messages),
            "bus_connected": bool(bus_connected),
            "sender": sender,
            "bitrate": bitrate,
            "registered_ids": list(registered_ids),
            "skipped_ids": list(skipped_ids),
        },
    )


def error_message(
    *,
    code: str,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> GatewayIPCMessage:
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if details:
        payload["details"] = dict(details)
    return GatewayIPCMessage(type="error", payload=payload)