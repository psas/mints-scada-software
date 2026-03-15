from __future__ import annotations

import threading
from copy import deepcopy
from typing import Any, Iterable, Mapping

from .models import BackendRuntimeState


class StateStore:
    """Minimal authoritative backend runtime state."""

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
        sender: str | None = None,
        bitrate: int | None = None,
        registered_ids: Iterable[str] | None = None,
        skipped_ids: Iterable[str] | None = None,
    ) -> None:
        with self._lock:
            self._state.bus.connected = connected
            self._state.bus.reconnecting = reconnecting
            self._state.bus.last_transition_wall_time = wall_time

            if sender is not None:
                self._state.bus.sender = sender
            if bitrate is not None:
                self._state.bus.bitrate = bitrate

            if registered_ids is not None:
                ids = list(registered_ids)
                self._state.bus.registered_ids = ids
                self._state.bus.registered_count = len(ids)

            if skipped_ids is not None:
                ids = list(skipped_ids)
                self._state.bus.skipped_ids = ids
                self._state.bus.skipped_count = len(ids)

    def set_device_inventory(
        self,
        *,
        devices: list[Mapping[str, Any]],
        load_errors: list[str] | None = None,
    ) -> None:
        with self._lock:
            self._state.device_registry.devices = [dict(device) for device in devices]
            self._state.device_registry.total_devices = len(devices)
            self._state.device_registry.load_errors = list(load_errors or [])
            self._state.device_registry.load_error_count = len(self._state.device_registry.load_errors)

    def mark_device_packet(
        self,
        *,
        device_id: str,
        wall_time: str,
        packet_id: int,
        packet_seq: int,
        packet_cmd: int,
        packet_reply: bool,
        packet_err: bool,
        packet_rsvd: bool,
        packet_timestamp: float | None,
        packet_data: list[int],
        runtime_value: Any,
        runtime_aux: Any,
        runtime_time: Any,
        source: str,
    ) -> None:
        with self._lock:
            current = self._state.device_runtime.by_id.get(device_id, {})
            packet_count = int(current.get("packet_count", 0)) + 1

            self._state.device_runtime.by_id[device_id] = {
                "device_id": device_id,
                "online": True,
                "source": source,
                "packet_count": packet_count,
                "last_packet_wall_time": wall_time,
                "last_packet_id": packet_id,
                "last_packet_seq": packet_seq,
                "last_packet_cmd": packet_cmd,
                "last_packet_reply": packet_reply,
                "last_packet_err": packet_err,
                "last_packet_rsvd": packet_rsvd,
                "last_packet_timestamp": packet_timestamp,
                "last_packet_data": list(packet_data),
                "last_packet_data_hex": " ".join(f"{b:02X}" for b in packet_data),
                "runtime_value": runtime_value,
                "runtime_aux": runtime_aux,
                "runtime_time": runtime_time,
            }

    def mark_script_started(
        self,
        *,
        script_id: str,
        name: str,
        pid: int,
        launch_mode: str,
        command: list[str],
        cwd: str | None,
        started_wall_time: str,
        current_step_index: int | None = None,
        total_steps: int | None = None,
        current_step_name: str | None = None,
        current_step_type: str | None = None,
        current_step_status: str | None = None,
        plan_steps_summary: list[str] | None = None,
    ) -> None:
        with self._lock:
            self._state.script_runner.is_running = True
            self._state.script_runner.script_id = script_id
            self._state.script_runner.name = name
            self._state.script_runner.pid = pid
            self._state.script_runner.launch_mode = launch_mode
            self._state.script_runner.command = list(command)
            self._state.script_runner.cwd = cwd
            self._state.script_runner.started_wall_time = started_wall_time
            self._state.script_runner.finished_wall_time = None
            self._state.script_runner.last_exit_code = None
            self._state.script_runner.last_stop_reason = None
            self._state.script_runner.current_step_index = current_step_index
            self._state.script_runner.total_steps = total_steps
            self._state.script_runner.current_step_name = current_step_name
            self._state.script_runner.current_step_type = current_step_type
            self._state.script_runner.current_step_status = current_step_status
            self._state.script_runner.last_progress_wall_time = started_wall_time
            self._state.script_runner.plan_steps_summary = list(plan_steps_summary or [])

    def mark_script_finished(
        self,
        *,
        finished_wall_time: str,
        return_code: int | None,
        reason: str,
    ) -> None:
        with self._lock:
            self._state.script_runner.is_running = False
            self._state.script_runner.finished_wall_time = finished_wall_time
            self._state.script_runner.last_exit_code = return_code
            self._state.script_runner.last_stop_reason = reason


    def update_script_progress(
        self,
        *,
        current_step_index: int | None,
        total_steps: int | None,
        current_step_name: str | None,
        current_step_type: str | None,
        current_step_status: str | None,
        progress_wall_time: str,
        plan_steps_summary: list[str] | None = None,
    ) -> None:
        with self._lock:
            self._state.script_runner.current_step_index = current_step_index
            self._state.script_runner.total_steps = total_steps
            self._state.script_runner.current_step_name = current_step_name
            self._state.script_runner.current_step_type = current_step_type
            self._state.script_runner.current_step_status = current_step_status
            self._state.script_runner.last_progress_wall_time = progress_wall_time
            if plan_steps_summary is not None:
                self._state.script_runner.plan_steps_summary = list(plan_steps_summary)

    def clear_script_running_state(self) -> None:
        with self._lock:
            self._state.script_runner.is_running = False
            self._state.script_runner.script_id = None
            self._state.script_runner.name = None
            self._state.script_runner.pid = None
            self._state.script_runner.launch_mode = None
            self._state.script_runner.command = []
            self._state.script_runner.cwd = None
            self._state.script_runner.current_step_index = None
            self._state.script_runner.total_steps = None
            self._state.script_runner.current_step_name = None
            self._state.script_runner.current_step_type = None
            self._state.script_runner.current_step_status = None
            self._state.script_runner.last_progress_wall_time = None
            self._state.script_runner.plan_steps_summary = []

    def set_health_snapshot(
        self,
        *,
        sampled_at: str,
        overall_status: str,
        active_warnings: list[str],
        writers: Mapping[str, Any],
        bus: Mapping[str, Any],
        script: Mapping[str, Any],
    ) -> None:
        with self._lock:
            self._state.health.sampled_at = sampled_at
            self._state.health.overall_status = overall_status
            self._state.health.active_warnings = list(active_warnings)
            self._state.health.active_warning_count = len(active_warnings)
            self._state.health.writers = {
                str(name): dict(value)
                for name, value in writers.items()
            }
            self._state.health.bus = dict(bus)
            self._state.health.script = dict(script)

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
                "health_summary": {
                    "sampled_at": self._state.health.sampled_at,
                    "overall_status": self._state.health.overall_status,
                    "active_warning_count": self._state.health.active_warning_count,
                    "active_warnings": list(self._state.health.active_warnings),
                },
            }
