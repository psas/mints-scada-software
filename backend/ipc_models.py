# backend/ipc_models.py

"""Backend IPC message models and outbound message builders.

This module defines the line-delimited JSON message envelope used by the
backend IPC server and provides small builders for the canonical message types
the backend emits to GUI clients and other IPC peers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class IPCMessage:
    """Immutable backend IPC message envelope.

    The backend IPC server serializes each message as a single JSON object with
    top-level ``type`` and ``payload`` keys. Incoming requests are parsed back
    into this envelope before dispatch.

    Attributes:
        type: Canonical message type string.
        payload: Message-specific payload object.
    """

    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Build a plain dictionary representation of the message.

        Returns:
            A new dictionary containing the message ``type`` and a shallow copy
            of ``payload``.
        """
        return {
            "type": self.type,
            "payload": dict(self.payload),
        }

    def to_json(self) -> str:
        """Serialize the message envelope to JSON for IPC transport.

        Returns:
            A JSON string containing the message envelope.
        """
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=False)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IPCMessage":
        """Build an IPC message from a decoded mapping.

        Args:
            data: Decoded message object with top-level ``type`` and optional
                ``payload`` fields.

        Returns:
            A validated ``IPCMessage`` instance.

        Raises:
            ValueError: If ``type`` is missing or empty, or if ``payload`` is
                present but is not a mapping.
        """
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
        """Decode an IPC message from a JSON string.

        Args:
            raw: Raw JSON message read from the IPC transport.

        Returns:
            A validated ``IPCMessage`` instance.

        Raises:
            ValueError: If the decoded JSON value is not an object-shaped
                mapping or if the decoded message fails ``from_dict``
                validation.
            json.JSONDecodeError: If ``raw`` is not valid JSON.
        """
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
    client_session: Mapping[str, Any] | None = None,
    connected_client_sessions: list[Mapping[str, Any]] | None = None,
) -> IPCMessage:
    """Build the backend hello acknowledgement message.

    Args:
        service_name: Backend service identifier reported to the client.
        backend_started_at: Backend process start timestamp.
        connected_clients: Current connected-client count.
        supported_messages: Message types this backend instance accepts.
        client_session: Session metadata for the client that sent ``hello``.
        connected_client_sessions: Session metadata for all connected clients
            known to the backend.

    Returns:
        A ``hello_ack`` IPC message.
    """
    return IPCMessage(
        type="hello_ack",
        payload={
            "service_name": service_name,
            "backend_started_at": backend_started_at,
            "connected_clients": connected_clients,
            "supported_messages": list(supported_messages),
            "client_session": dict(client_session or {}),
            "connected_client_sessions": [
                dict(item) for item in list(connected_client_sessions or [])
            ],
        },
    )


def backend_status_message(
    *,
    backend_started_at: str,
    connected_clients: int,
    active_run_id: str | None,
    is_running: bool,
    connected_client_sessions: list[Mapping[str, Any]] | None = None,
    health_summary: Mapping[str, Any] | None = None,
    recording: Mapping[str, Any] | None = None,
    mission_clock: Mapping[str, Any] | None = None,
    playback_clock: Mapping[str, Any] | None = None,
    run_mode: str | None = None,
    last_command: Mapping[str, Any] | None = None,
) -> IPCMessage:
    """Build the backend runtime status message.

    Args:
        backend_started_at: Backend process start timestamp.
        connected_clients: Current connected-client count.
        active_run_id: Active run identifier, if a run is open.
        is_running: Whether a run is currently active.
        connected_client_sessions: Session metadata for connected clients.
        health_summary: Current backend health summary snapshot.
        recording: Recording-status snapshot from backend runtime state.
        mission_clock: Mission clock snapshot from backend runtime state.
        playback_clock: Playback clock snapshot from backend runtime state.
        run_mode: Current backend run mode.
        last_command: Summary of the most recent routed command.

    Returns:
        A ``backend_status`` IPC message.
    """
    return IPCMessage(
        type="backend_status",
        payload={
            "backend_started_at": backend_started_at,
            "connected_clients": connected_clients,
            "active_run_id": active_run_id,
            "is_running": is_running,
            "run_mode": run_mode,
            "connected_client_sessions": [
                dict(item) for item in list(connected_client_sessions or [])
            ],
            "health_summary": dict(health_summary or {}),
            "recording": dict(recording or {}),
            "mission_clock": dict(mission_clock or {}),
            "playback_clock": dict(playback_clock or {}),
            "last_command": dict(last_command or {}),
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
    """Build a run lifecycle status message.

    Args:
        run_id: Run identifier.
        mode: Run mode associated with the status update.
        status: Current lifecycle status for the run.
        test_name: Recorded test name, when available.
        operator: Operator name associated with the run.
        profile_name: Selected profile name, when available.
        reason: Reason for the current lifecycle transition.
        started_wall_time: Run start timestamp, when known.
        finished_wall_time: Run finish timestamp, when known.

    Returns:
        A ``run_status`` IPC message.
    """
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
    """Wrap a backend state snapshot for IPC delivery.

    Args:
        snapshot: Authoritative backend runtime state snapshot.

    Returns:
        A ``state_snapshot`` IPC message.
    """
    return IPCMessage(type="state_snapshot", payload=dict(snapshot))


def structured_event_message(event: Mapping[str, Any]) -> IPCMessage:
    """Wrap a structured backend event for IPC delivery.

    Args:
        event: Structured event payload emitted by the backend.

    Returns:
        A ``structured_event`` IPC message.
    """
    return IPCMessage(type="structured_event", payload=dict(event))


def operator_action_recorded_message(action: Mapping[str, Any]) -> IPCMessage:
    """Wrap a recorded operator action for IPC delivery.

    Args:
        action: Canonical operator action payload recorded by the backend.

    Returns:
        A ``operator_action_recorded`` IPC message.
    """
    return IPCMessage(type="operator_action_recorded", payload=dict(action))


def command_result_message(
    *,
    success: bool,
    command_name: str,
    device_id: str | None,
    dispatched_via: str,
    result_summary: Any = None,
    error: str | None = None,
    status: str | None = None,
    adapter_name: str | None = None,
    rejection_reason: str | None = None,
    interlock_reason: str | None = None,
    validation_errors: list[str] | None = None,
    state_reasons: list[str] | None = None,
    request_id: str | None = None,
    request_source: str | None = None,
    authority_level: str | None = None,
    run_mode: str | None = None,
    requested_at: str | None = None,
) -> IPCMessage:
    """Build a canonical command-result message.

    Args:
        success: Whether the command was accepted and completed successfully.
        command_name: Canonical command name.
        device_id: Target device identifier, when the command targets a device.
        dispatched_via: Dispatch path or adapter that handled the command.
        result_summary: Command-specific result payload.
        error: Error summary for failed execution paths.
        status: Command status string.
        adapter_name: Adapter name used for the command path.
        rejection_reason: Validation or policy rejection reason.
        interlock_reason: Interlock-specific rejection reason.
        validation_errors: Validation error strings collected during routing.
        state_reasons: State-based reasons collected during routing.
        request_id: Request identifier propagated with the command.
        request_source: Logical source that requested the command.
        authority_level: Authority level associated with the request.
        run_mode: Run mode active when the command was requested.
        requested_at: Request timestamp.

    Returns:
        A ``command_result`` IPC message.
    """
    return IPCMessage(
        type="command_result",
        payload={
            "success": success,
            "command_name": command_name,
            "device_id": device_id,
            "dispatched_via": dispatched_via,
            "result_summary": result_summary,
            "error": error,
            "status": status,
            "adapter_name": adapter_name,
            "rejection_reason": rejection_reason,
            "interlock_reason": interlock_reason,
            "validation_errors": list(validation_errors or []),
            "state_reasons": list(state_reasons or []),
            "request_id": request_id,
            "request_source": request_source,
            "authority_level": authority_level,
            "run_mode": run_mode,
            "requested_at": requested_at,
        },
    )


def script_status_message(
    *,
    status: str,
    script_id: str | None,
    name: str | None,
    pid: int | None,
    launch_mode: str | None = None,
    command: list[str] | None = None,
    cwd: str | None = None,
    returncode: int | None = None,
    reason: str | None = None,
    current_step_index: int | None = None,
    total_steps: int | None = None,
    current_step_name: str | None = None,
    current_step_type: str | None = None,
    current_step_status: str | None = None,
    plan_steps_summary: list[str] | None = None,
    is_held: bool | None = None,
    hold_requested: bool | None = None,
) -> IPCMessage:
    """Build a script runtime status message.

    Args:
        status: Current script runtime status.
        script_id: Backend-assigned script identifier.
        name: Display name of the script.
        pid: Runtime process identifier, when a process exists.
        launch_mode: Script launch mode.
        command: Full subprocess command line.
        cwd: Working directory used for the script launch.
        returncode: Process exit code, when the script has finished.
        reason: Human-readable reason for the current status.
        current_step_index: Active plan-step index, when available.
        total_steps: Total number of plan steps, when available.
        current_step_name: Active step display name.
        current_step_type: Active step type.
        current_step_status: Active step execution status.
        plan_steps_summary: Display-oriented summary for all plan steps.
        is_held: Whether the script is currently held.
        hold_requested: Whether a hold has been requested but not yet resolved.

    Returns:
        A ``script_status`` IPC message.
    """
    return IPCMessage(
        type="script_status",
        payload={
            "status": status,
            "script_id": script_id,
            "name": name,
            "pid": pid,
            "launch_mode": launch_mode,
            "command": list(command or []),
            "cwd": cwd,
            "returncode": returncode,
            "reason": reason,
            "current_step_index": current_step_index,
            "total_steps": total_steps,
            "current_step_name": current_step_name,
            "current_step_type": current_step_type,
            "current_step_status": current_step_status,
            "plan_steps_summary": list(plan_steps_summary or []),
            "is_held": is_held,
            "hold_requested": hold_requested,
        },
    )


def device_inventory_message(
    *,
    total_devices: int,
    load_error_count: int,
    load_errors: list[str],
    devices: list[Mapping[str, Any]],
) -> IPCMessage:
    """Build the backend device inventory message.

    Args:
        total_devices: Number of devices included in the inventory snapshot.
        load_error_count: Number of device-catalog load errors.
        load_errors: Human-readable load errors collected during inventory load.
        devices: GUI-facing device presentation payloads.

    Returns:
        A ``device_inventory`` IPC message.
    """
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
    """Build the live-hardware registration status message.

    Args:
        connected: Whether the live hardware link is currently connected.
        sender: Hardware sender/backend identifier reported with the status.
        bitrate: Configured or detected bus bitrate.
        registered_ids: Device IDs successfully registered for live hardware.
        skipped_ids: Device IDs skipped during live registration.

    Returns:
        A ``hardware_status`` IPC message that also includes registered and
        skipped counts derived from the provided ID lists.
    """
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
    """Build the backend ping response message.

    Returns:
        A ``pong`` IPC message.
    """
    return IPCMessage(type="pong", payload={})


def error_message(code: str, message: str) -> IPCMessage:
    """Build a canonical IPC error message.

    Args:
        code: Stable error code for the failure.
        message: Human-readable error summary.

    Returns:
        An ``error`` IPC message.
    """
    return IPCMessage(
        type="error",
        payload={
            "code": code,
            "message": message,
        },
    )
