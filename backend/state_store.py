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