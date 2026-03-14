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
    last_started_wall_time: str | None = None
    last_finished_wall_time: str | None = None
    last_finish_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
class BackendRuntimeState:
    service_name: str
    backend_started_at: str
    connected_clients: int = 0
    run: RunRuntimeState = field(default_factory=RunRuntimeState)
    bus: BusRuntimeState = field(default_factory=BusRuntimeState)
    device_registry: DeviceRegistryState = field(default_factory=DeviceRegistryState)
    device_runtime: DeviceRuntimeState = field(default_factory=DeviceRuntimeState)

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_name": self.service_name,
            "backend_started_at": self.backend_started_at,
            "connected_clients": self.connected_clients,
            "run": self.run.to_dict(),
            "bus": self.bus.to_dict(),
            "device_registry": self.device_registry.to_dict(),
            "device_runtime": self.device_runtime.to_dict(),
        }