from __future__ import annotations

import threading
from copy import deepcopy
from typing import Any

from .models import BackendRuntimeState


class StateStore:
    """Minimal authoritative backend runtime state.

    Commit 5 scope:
    - backend identity
    - connected client count
    - minimal run lifecycle state
    - minimal bus connection state placeholder

    Bus/reducer/device state will be added in later commits.
    """

    def __init__(self, *, service_name: str, backend_started_at: str) -> None:
        self._lock = threading.RLock()
        self._state = BackendRuntimeState(
            service_name=service_name,
            backend_started_at=backend_started_at,
        )

    def set_connected_clients(self, count: int) -> None:
        with self._lock:
            self._state.connected_clients = max(0, int(count))

    def mark_run_started(
        self,
        *,
        run_id: str,
        mode: str,
        test_name: str,
        operator: str | None,
        profile_name: str | None,
        started_wall_time: str,
    ) -> None:
        with self._lock:
            self._state.run.active_run_id = run_id
            self._state.run.is_running = True
            self._state.run.mode = mode
            self._state.run.status = "running"
            self._state.run.test_name = test_name
            self._state.run.operator = operator
            self._state.run.profile_name = profile_name
            self._state.run.last_started_wall_time = started_wall_time
            self._state.run.last_finish_reason = None

    def mark_run_finished(
        self,
        *,
        run_id: str,
        finished_wall_time: str,
        reason: str,
    ) -> None:
        with self._lock:
            # Keep the last active run id visible until a new run starts.
            self._state.run.active_run_id = run_id
            self._state.run.is_running = False
            self._state.run.status = "completed"
            self._state.run.last_finished_wall_time = finished_wall_time
            self._state.run.last_finish_reason = reason

    def set_bus_connection_state(
        self,
        *,
        connected: bool,
        reconnecting: bool,
        wall_time: str | None,
    ) -> None:
        with self._lock:
            self._state.bus.connected = connected
            self._state.bus.reconnecting = reconnecting
            self._state.bus.last_transition_wall_time = wall_time

    def get_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state.to_dict())

    def get_backend_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "backend_started_at": self._state.backend_started_at,
                "connected_clients": self._state.connected_clients,
                "active_run_id": self._state.run.active_run_id,
                "is_running": self._state.run.is_running,
            }
