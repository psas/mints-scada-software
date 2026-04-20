"""gateway/ipc_models.py

IPC message models and builders for backend/gateway communication.

This module defines the JSON-lines message envelope used on the gateway IPC
boundary and provides small builders for the canonical message types emitted by
the gateway service.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


@dataclass(slots=True)
class GatewayIPCMessage:
    """Represent a single backend/gateway IPC message.

    Attributes:
        type: Canonical IPC message type name.
        payload: JSON-serializable message payload.
    """

    type: str
    payload: dict[str, Any] = field(default_factory=dict)


def encode_message(message: GatewayIPCMessage) -> bytes:
    """Encode an IPC message into canonical JSON-lines bytes.

    Args:
        message: IPC message to serialize.

    Returns:
        UTF-8 encoded JSON bytes containing the message type and payload.
    """
    return json.dumps(
        {
            "type": message.type,
            "payload": dict(message.payload),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def decode_message(raw: bytes | str) -> GatewayIPCMessage:
    """Decode a raw JSON IPC frame into a typed message object.

    Args:
        raw: Raw IPC data as UTF-8 bytes or decoded text.

    Returns:
        The decoded IPC message.

    Raises:
        ValueError: If the decoded JSON is not an object, if ``type`` is not a
            non-empty string, or if ``payload`` is not a JSON object.
    """
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
    """Build the gateway hello acknowledgement message.

    Args:
        service_name: Gateway service name reported to the client.
        gateway_started_at: Gateway process start timestamp.
        connected_clients: Number of clients currently connected to the gateway.
        supported_messages: Message types supported by the gateway IPC server.

    Returns:
        A ``hello_ack`` IPC message.
    """
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
    """Build the gateway ping response message.

    Returns:
        A ``pong`` IPC message with an empty payload.
    """
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
    """Build a gateway hardware status update message.

    The builder canonicalizes registered and skipped device identifiers into
    lists of strings and fills in the count fields when they are not supplied.

    Args:
        connected: Whether the live hardware link is currently connected.
        sender: Backend or bus sender label associated with the status.
        bitrate: Active bus bitrate when known.
        registered_ids: Device identifiers successfully registered on the bus.
        skipped_ids: Device identifiers skipped during registration.
        reconnecting: Whether the gateway is currently trying to reconnect.
        status: Explicit status label. Defaults to ``"connected"`` or
            ``"disconnected"`` based on ``connected``.
        reason: Optional explanatory status detail.
        registered_count: Explicit registered-device count override.
        skipped_count: Explicit skipped-device count override.
        already_running: Whether live hardware was already running when the
            request was handled.
        packet_listener_attached: Whether the packet listener is attached.
        wall_time: Wall-clock timestamp for the status snapshot.

    Returns:
        A ``hardware_status`` IPC message.
    """
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
    """Build a packet-sent notification for an outbound bus command.

    Args:
        device_id: Canonical target device identifier when known.
        packet_id: Outbound packet identifier.
        seq: Outbound packet sequence value.
        cmd: Outbound packet command value.
        sender: Sender label associated with the packet.
        bitrate: Active bus bitrate when known.

    Returns:
        A ``packet_sent`` IPC message.
    """
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
    """Build the gateway raw-run start notification.

    Args:
        run_id: Active raw run identifier.
        mode: Run mode reported by the gateway.
        status: Run status label.
        test_name: Test name associated with the run.
        operator: Operator name associated with the run.
        profile_name: Selected profile name when present.
        started_wall_time: Wall-clock timestamp for run start.

    Returns:
        A ``run_started`` IPC message.
    """
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
    """Build the gateway raw-run finish notification.

    Args:
        run_id: Finished raw run identifier.
        mode: Run mode reported by the gateway.
        status: Final run status label.
        test_name: Test name associated with the run.
        reason: Optional finish reason.
        finished_wall_time: Wall-clock timestamp for run finish.

    Returns:
        A ``run_finished`` IPC message.
    """
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
    """Build a raw-event recording result message.

    Args:
        stream_name: Raw stream name that received the event.
        run_id: Active raw run identifier when one exists.
        accepted: Whether the raw event was accepted for recording.
        event: Recorded event payload when it should be echoed to the caller.

    Returns:
        A ``raw_event_recorded`` IPC message.
    """
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
    """Build the gateway abort result message.

    Args:
        ok: Whether the abort request handling succeeded.
        abort_latched: Whether the gateway abort latch is set after handling.
        relay_request_id: Relay request identifier associated with the abort.
        relay_session_id: Relay session identifier associated with the abort.
        backend_forwarded: Whether the request was forwarded to the backend.
        backend_error: Backend forwarding error when one occurred.
        placeholder_message: Placeholder abort text used by the current gateway
            abort path when present.
        wall_time: Wall-clock timestamp for the result.

    Returns:
        A canonical ``abort_result`` IPC message.
    """
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


def clear_abort_latch_result_message(
    *,
    ok: bool,
    abort_latched: bool,
    was_latched: bool,
    relay_request_id: str | None,
    relay_session_id: str | None,
    backend_forwarded: bool,
    backend_error: str | None = None,
    message: str | None = None,
    wall_time: str | None = None,
) -> GatewayIPCMessage:
    """Build the gateway clear-abort-latch result message.

    Args:
        ok: Whether the clear request handling succeeded.
        abort_latched: Whether the abort latch remains set after handling.
        was_latched: Whether the abort latch was set before handling.
        relay_request_id: Relay request identifier associated with the request.
        relay_session_id: Relay session identifier associated with the request.
        backend_forwarded: Whether the request was forwarded to the backend.
        backend_error: Backend forwarding error when one occurred.
        message: Optional result detail message.
        wall_time: Wall-clock timestamp for the result.

    Returns:
        A ``clear_abort_latch_result`` IPC message.
    """
    payload: dict[str, Any] = {
        "ok": bool(ok),
        "abort_latched": bool(abort_latched),
        "was_latched": bool(was_latched),
        "backend_forwarded": bool(backend_forwarded),
        "relay_request_id": relay_request_id,
        "relay_session_id": relay_session_id,
        "wall_time": wall_time,
    }
    if backend_error is not None:
        payload["backend_error"] = backend_error
    if message is not None:
        payload["message"] = message
    return GatewayIPCMessage(type="clear_abort_latch_result", payload=payload)


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
    """Build a full gateway status snapshot message.

    Args:
        service_name: Gateway service name.
        gateway_started_at: Gateway process start timestamp.
        socket_path: Gateway IPC socket path.
        connected_clients: Number of currently connected IPC clients.
        supported_messages: Message types supported by the gateway IPC server.
        bus_connected: Whether the live bus link is connected.
        sender: Backend or bus sender label when known.
        bitrate: Active bus bitrate when known.
        registered_ids: Device identifiers currently registered on the bus.
        skipped_ids: Device identifiers skipped during registration.
        raw_run_active: Whether a raw run is currently active.
        raw_run_id: Active raw run identifier when one exists.
        raw_mode: Active raw run mode when one exists.
        raw_test_name: Active raw run test name when one exists.
        raw_started_wall_time: Wall-clock timestamp for active raw run start.
        backend_link_ok: Whether the backend link is currently healthy.
        abort_latched: Whether the gateway abort latch is set.
        abort_latched_at: Wall-clock timestamp when the abort latch was set.
        abort_relay_request_id: Relay request identifier associated with the
            current abort latch.

    Returns:
        A ``gateway_status`` IPC message.
    """
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
    """Build a canonical IPC error message.

    Args:
        code: Stable error code.
        message: Human-readable error summary.
        details: Optional structured error details.

    Returns:
        An ``error`` IPC message.
    """
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if details:
        payload["details"] = dict(details)
    return GatewayIPCMessage(type="error", payload=payload)
