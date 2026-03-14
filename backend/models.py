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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BackendRuntimeState:
    service_name: str
    backend_started_at: str
    connected_clients: int = 0
    run: RunRuntimeState = field(default_factory=RunRuntimeState)
    bus: BusRuntimeState = field(default_factory=BusRuntimeState)

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_name": self.service_name,
            "backend_started_at": self.backend_started_at,
            "connected_clients": self.connected_clients,
            "run": self.run.to_dict(),
            "bus": self.bus.to_dict(),
        }
