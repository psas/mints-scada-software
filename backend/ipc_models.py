from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class IPCMessage:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "payload": dict(self.payload),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IPCMessage":
        message_type = data.get("type")
        if not isinstance(message_type, str) or not message_type.strip():
            raise ValueError("IPC message must contain a non-empty string 'type'")

        payload = data.get("payload", {})
        if payload is None:
            payload = {}
        if not isinstance(payload, Mapping):
            raise ValueError("IPC message 'payload' must be a mapping")

        return cls(type=message_type, payload=dict(payload))

    @classmethod
    def from_json(cls, raw: str) -> "IPCMessage":
        data = json.loads(raw)
        if not isinstance(data, Mapping):
            raise ValueError("IPC message JSON must decode to an object")
        return cls.from_dict(data)


def hello_ack_message(
    *,
    service_name: str,
    backend_started_at: str,
    connected_clients: int,
    supported_messages: list[str],
) -> IPCMessage:
    return IPCMessage(
        type="hello_ack",
        payload={
            "service_name": service_name,
            "backend_started_at": backend_started_at,
            "connected_clients": connected_clients,
            "supported_messages": list(supported_messages),
        },
    )


def backend_status_message(
    *,
    backend_started_at: str,
    connected_clients: int,
    active_run_id: str | None,
    is_running: bool,
) -> IPCMessage:
    return IPCMessage(
        type="backend_status",
        payload={
            "backend_started_at": backend_started_at,
            "connected_clients": connected_clients,
            "active_run_id": active_run_id,
            "is_running": is_running,
        },
    )


def run_status_message(
    *,
    run_id: str,
    mode: str | None,
    status: str,
    test_name: str | None = None,
    operator: str | None = None,
    profile_name: str | None = None,
    reason: str | None = None,
    started_wall_time: str | None = None,
    finished_wall_time: str | None = None,
) -> IPCMessage:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "mode": mode,
        "status": status,
        "test_name": test_name,
        "operator": operator,
        "profile_name": profile_name,
        "reason": reason,
        "started_wall_time": started_wall_time,
        "finished_wall_time": finished_wall_time,
    }
    return IPCMessage(type="run_status", payload=payload)


def state_snapshot_message(snapshot: Mapping[str, Any]) -> IPCMessage:
    return IPCMessage(
        type="state_snapshot",
        payload=dict(snapshot),
    )


def device_inventory_message(
    *,
    total_devices: int,
    load_error_count: int,
    load_errors: list[str],
    devices: list[Mapping[str, Any]],
) -> IPCMessage:
    return IPCMessage(
        type="device_inventory",
        payload={
            "total_devices": total_devices,
            "load_error_count": load_error_count,
            "load_errors": list(load_errors),
            "devices": [dict(device) for device in devices],
        },
    )


def hardware_status_message(
    *,
    connected: bool,
    sender: str | None,
    bitrate: int | None,
    registered_ids: list[str],
    skipped_ids: list[str],
) -> IPCMessage:
    return IPCMessage(
        type="hardware_status",
        payload={
            "connected": connected,
            "sender": sender,
            "bitrate": bitrate,
            "registered_ids": list(registered_ids),
            "skipped_ids": list(skipped_ids),
            "registered_count": len(registered_ids),
            "skipped_count": len(skipped_ids),
        },
    )


def pong_message() -> IPCMessage:
    return IPCMessage(type="pong", payload={})


def error_message(code: str, message: str) -> IPCMessage:
    return IPCMessage(
        type="error",
        payload={
            "code": code,
            "message": message,
        },
    )