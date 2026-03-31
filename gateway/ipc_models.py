from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


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
    sender: str | None = None,
    bitrate: int | None = None,
    registered_ids: Iterable[str] | None = None,
    skipped_ids: Iterable[str] | None = None,
    reconnecting: bool = False,
    status: str | None = None,
    reason: str | None = None,
    registered_count: int | None = None,
    skipped_count: int | None = None,
    already_running: bool | None = None,
    packet_listener_attached: bool | None = None,
    wall_time: str | None = None,
) -> GatewayIPCMessage:
    registered_list = [str(x) for x in (registered_ids or [])]
    skipped_list = [str(x) for x in (skipped_ids or [])]

    if registered_count is None:
        registered_count = len(registered_list)
    if skipped_count is None:
        skipped_count = len(skipped_list)
    if status is None:
        status = "connected" if connected else "disconnected"

    return GatewayIPCMessage(
        type="hardware_status",
        payload={
            "connected": bool(connected),
            "reconnecting": bool(reconnecting),
            "status": str(status),
            "reason": reason,
            "sender": sender,
            "bitrate": bitrate,
            "registered_ids": registered_list,
            "skipped_ids": skipped_list,
            "registered_count": int(registered_count),
            "skipped_count": int(skipped_count),
            "already_running": already_running,
            "packet_listener_attached": packet_listener_attached,
            "wall_time": wall_time,
        },
    )


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


def run_started_message(
    *,
    run_id: str,
    mode: str,
    status: str,
    test_name: str | None = None,
    operator: str | None = None,
    profile_name: str | None = None,
    started_wall_time: str | None = None,
) -> GatewayIPCMessage:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "mode": mode,
        "status": status,
    }
    if test_name is not None:
        payload["test_name"] = test_name
    if operator is not None:
        payload["operator"] = operator
    if profile_name is not None:
        payload["profile_name"] = profile_name
    if started_wall_time is not None:
        payload["started_wall_time"] = started_wall_time
    return GatewayIPCMessage(type="run_started", payload=payload)


def run_finished_message(
    *,
    run_id: str,
    mode: str,
    status: str,
    test_name: str | None = None,
    reason: str | None = None,
    finished_wall_time: str | None = None,
) -> GatewayIPCMessage:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "mode": mode,
        "status": status,
    }
    if test_name is not None:
        payload["test_name"] = test_name
    if reason is not None:
        payload["reason"] = reason
    if finished_wall_time is not None:
        payload["finished_wall_time"] = finished_wall_time
    return GatewayIPCMessage(type="run_finished", payload=payload)


def raw_event_recorded_message(
    *,
    stream_name: str,
    run_id: str | None,
    accepted: bool = True,
    event: Mapping[str, Any] | None = None,
) -> GatewayIPCMessage:
    payload: dict[str, Any] = {
        "stream_name": stream_name,
        "accepted": bool(accepted),
    }
    if run_id is not None:
        payload["run_id"] = run_id
    if event is not None:
        payload["event"] = dict(event)
    return GatewayIPCMessage(type="raw_event_recorded", payload=payload)


def abort_result_message(
    *,
    ok: bool,
    abort_latched: bool,
    relay_request_id: str | None,
    relay_session_id: str | None,
    backend_forwarded: bool,
    backend_error: str | None = None,
    placeholder_message: str | None = None,
    wall_time: str | None = None,
) -> GatewayIPCMessage:
    payload: dict[str, Any] = {
        "ok": bool(ok),
        "abort_latched": bool(abort_latched),
        "backend_forwarded": bool(backend_forwarded),
        "relay_request_id": relay_request_id,
        "relay_session_id": relay_session_id,
        "wall_time": wall_time,
    }
    if backend_error is not None:
        payload["backend_error"] = backend_error
    if placeholder_message is not None:
        payload["placeholder_message"] = placeholder_message
    return GatewayIPCMessage(type="abort_result", payload=payload)


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
    raw_run_active: bool = False,
    raw_run_id: str | None = None,
    raw_mode: str | None = None,
    raw_test_name: str | None = None,
    raw_started_wall_time: str | None = None,
    backend_link_ok: bool | None = None,
    abort_latched: bool = False,
    abort_latched_at: str | None = None,
    abort_relay_request_id: str | None = None,
) -> GatewayIPCMessage:
    payload: dict[str, Any] = {
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
        "raw_run_active": bool(raw_run_active),
        "abort_latched": bool(abort_latched),
    }
    if raw_run_id is not None:
        payload["raw_run_id"] = raw_run_id
    if raw_mode is not None:
        payload["raw_mode"] = raw_mode
    if raw_test_name is not None:
        payload["raw_test_name"] = raw_test_name
    if raw_started_wall_time is not None:
        payload["raw_started_wall_time"] = raw_started_wall_time
    if backend_link_ok is not None:
        payload["backend_link_ok"] = bool(backend_link_ok)
    if abort_latched_at is not None:
        payload["abort_latched_at"] = abort_latched_at
    if abort_relay_request_id is not None:
        payload["abort_relay_request_id"] = abort_relay_request_id

    return GatewayIPCMessage(type="gateway_status", payload=payload)


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
