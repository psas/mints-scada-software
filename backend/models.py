from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RunRuntimeState:
    active_run_id: str | None = None
    is_running: bool = False
    mode: str | None = None
    status: str = "idle"
    test_name: str | None = None
    operator: str | None = None
    profile_name: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    last_started_wall_time: str | None = None
    last_finished_wall_time: str | None = None
    last_finish_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "metadata": dict(self.metadata),
        }


@dataclass
class BusRuntimeState:
    connected: bool = False
    reconnecting: bool = False
    last_transition_wall_time: str | None = None
    sender: str | None = None
    bitrate: int | None = None
    registered_count: int = 0
    registered_ids: list[str] = field(default_factory=list)
    skipped_count: int = 0
    skipped_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeviceRegistryState:
    total_devices: int = 0
    load_error_count: int = 0
    load_errors: list[str] = field(default_factory=list)
    devices: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_devices": self.total_devices,
            "load_error_count": self.load_error_count,
            "load_errors": list(self.load_errors),
            "devices": [dict(device) for device in self.devices],
        }


@dataclass
class DeviceRuntimeState:
    by_id: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "by_id": {
                device_id: dict(state)
                for device_id, state in self.by_id.items()
            }
        }


@dataclass
class GuiPresenceState:
    total_connections: int = 0
    total_windows: int = 0
    by_connection_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    window_roles: list[str] = field(default_factory=list)
    logical_client_ids: list[str] = field(default_factory=list)
    last_event_wall_time: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_connections": self.total_connections,
            "total_windows": self.total_windows,
            "by_connection_id": {
                connection_id: dict(value)
                for connection_id, value in self.by_connection_id.items()
            },
            "window_roles": list(self.window_roles),
            "logical_client_ids": list(self.logical_client_ids),
            "last_event_wall_time": self.last_event_wall_time,
        }


@dataclass
class RecordingClockState:
    active: bool = False
    status: str = "idle"
    started_wall_time: str | None = None
    stopped_wall_time: str | None = None
    elapsed_seconds: float = 0.0
    display_text: str = "Not Recording"
    accent: str = "neutral"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlaybackClockState:
    active: bool = False
    status: str = "idle"
    source_run_id: str | None = None
    total_duration_seconds: float | None = None
    position_seconds: float | None = None
    display_text: str = "Playback: --"
    accent: str = "neutral"
    started_wall_time: str | None = None
    updated_wall_time: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MissionClockState:
    label: str = "T+"
    state: str = "idle"
    seconds: float = 0.0
    updated_wall_time: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SequenceRuntimeState:
    current_state: str | None = None
    current_phase: str | None = None
    current_step_name: str | None = None
    current_step_index: int | None = None
    hold_state: str | None = None
    profile_name: str | None = None
    updated_wall_time: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "details": dict(self.details),
        }


@dataclass
class AlarmRuntimeState:
    active_alarm_count: int = 0
    active_fault_count: int = 0
    active_alarms: list[dict[str, Any]] = field(default_factory=list)
    active_faults: list[dict[str, Any]] = field(default_factory=list)
    updated_wall_time: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_alarm_count": self.active_alarm_count,
            "active_fault_count": self.active_fault_count,
            "active_alarms": [dict(item) for item in self.active_alarms],
            "active_faults": [dict(item) for item in self.active_faults],
            "updated_wall_time": self.updated_wall_time,
        }


@dataclass
class ScriptRunnerState:
    is_running: bool = False
    script_id: str | None = None
    name: str | None = None
    pid: int | None = None
    launch_mode: str | None = None
    command: list[str] = field(default_factory=list)
    cwd: str | None = None
    started_wall_time: str | None = None
    finished_wall_time: str | None = None
    last_exit_code: int | None = None
    last_stop_reason: str | None = None
    last_failure_message: str | None = None
    last_exit_status: str | None = None  # "completed" | "failed" | "stopped" | "exited"
    output_lines: list[str] = field(default_factory=list)
    current_step_index: int | None = None
    total_steps: int | None = None
    current_step_name: str | None = None
    current_step_type: str | None = None
    current_step_status: str | None = None
    last_progress_wall_time: str | None = None
    plan_steps_summary: list[str] = field(default_factory=list)
    is_held: bool = False
    hold_requested: bool = False
    last_hold_wall_time: str | None = None
    last_continue_wall_time: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HealthRuntimeState:
    sampled_at: str | None = None
    overall_status: str = "unknown"
    active_warning_count: int = 0
    active_warnings: list[str] = field(default_factory=list)
    writers: dict[str, dict[str, Any]] = field(default_factory=dict)
    bus: dict[str, Any] = field(default_factory=dict)
    script: dict[str, Any] = field(default_factory=dict)
    gui: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sampled_at": self.sampled_at,
            "overall_status": self.overall_status,
            "active_warning_count": self.active_warning_count,
            "active_warnings": list(self.active_warnings),
            "writers": {name: dict(value) for name, value in self.writers.items()},
            "bus": dict(self.bus),
            "script": dict(self.script),
            "gui": dict(self.gui),
        }


@dataclass
class CommandRuntimeState:
    request_id: str | None = None
    requested_at: str | None = None
    request_source: str | None = None
    authority_level: str | None = None
    command_name: str | None = None
    device_id: str | None = None
    status: str = "idle"
    dispatched_via: str | None = None
    adapter_name: str | None = None
    run_mode: str | None = None
    rejection_reason: str | None = None
    interlock_reason: str | None = None
    validation_errors: list[str] = field(default_factory=list)
    state_reasons: list[str] = field(default_factory=list)
    error: str | None = None
    result_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "requested_at": self.requested_at,
            "request_source": self.request_source,
            "authority_level": self.authority_level,
            "command_name": self.command_name,
            "device_id": self.device_id,
            "status": self.status,
            "dispatched_via": self.dispatched_via,
            "adapter_name": self.adapter_name,
            "run_mode": self.run_mode,
            "rejection_reason": self.rejection_reason,
            "interlock_reason": self.interlock_reason,
            "validation_errors": list(self.validation_errors),
            "state_reasons": list(self.state_reasons),
            "error": self.error,
            "result_summary": dict(self.result_summary),
        }


@dataclass
class BackendRuntimeState:
    service_name: str
    backend_started_at: str
    connected_clients: int = 0
    run: RunRuntimeState = field(default_factory=RunRuntimeState)
    bus: BusRuntimeState = field(default_factory=BusRuntimeState)
    device_registry: DeviceRegistryState = field(default_factory=DeviceRegistryState)
    device_runtime: DeviceRuntimeState = field(default_factory=DeviceRuntimeState)
    gui: GuiPresenceState = field(default_factory=GuiPresenceState)
    mission_clock: MissionClockState = field(default_factory=MissionClockState)
    recording_clock: RecordingClockState = field(default_factory=RecordingClockState)
    playback_clock: PlaybackClockState = field(default_factory=PlaybackClockState)
    sequence: SequenceRuntimeState = field(default_factory=SequenceRuntimeState)
    alarms: AlarmRuntimeState = field(default_factory=AlarmRuntimeState)
    script_runner: ScriptRunnerState = field(default_factory=ScriptRunnerState)
    health: HealthRuntimeState = field(default_factory=HealthRuntimeState)
    last_command: CommandRuntimeState = field(default_factory=CommandRuntimeState)

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_name": self.service_name,
            "backend_started_at": self.backend_started_at,
            "connected_clients": self.connected_clients,
            "run": self.run.to_dict(),
            "bus": self.bus.to_dict(),
            "device_registry": self.device_registry.to_dict(),
            "device_runtime": self.device_runtime.to_dict(),
            "gui": self.gui.to_dict(),
            "mission_clock": self.mission_clock.to_dict(),
            "recording_clock": self.recording_clock.to_dict(),
            "playback_clock": self.playback_clock.to_dict(),
            "sequence": self.sequence.to_dict(),
            "alarms": self.alarms.to_dict(),
            "script_runner": self.script_runner.to_dict(),
            "health": self.health.to_dict(),
            "last_command": self.last_command.to_dict(),
        }
