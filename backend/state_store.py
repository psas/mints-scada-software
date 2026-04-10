# backend/state_store.py

"""Authoritative backend runtime state and time-format helpers.

This module stores the backend-owned runtime snapshot that is exposed to GUI
clients and other backend subsystems. It tracks run lifecycle, GUI session
presence, device runtime shadows, clocks, alarms, script execution state,
command results, and health summaries, and it computes transient display fields
when snapshots are requested.
"""

from __future__ import annotations

import threading
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .models import BackendRuntimeState


class StateStore:
    """Own the authoritative backend runtime snapshot.

    The store centralizes backend-owned state that GUI clients and other
    backend subsystems consume through snapshot reads. It also refreshes
    transient fields such as GUI presence, packet ages, and recording/playback
    clock display text before snapshots are returned.
    """

    def __init__(self, *, service_name: str, backend_started_at: str) -> None:
        """Initialize the runtime state container.

        Args:
            service_name: Backend service name recorded in the state snapshot.
            backend_started_at: ISO wall-clock timestamp for backend startup.
        """
        self._lock = threading.RLock()
        self._state = BackendRuntimeState(
            service_name=service_name,
            backend_started_at=backend_started_at,
        )

    def set_connected_clients(self, count: int) -> None:
        """Update the current backend connection count.

        This also mirrors the normalized count into the GUI summary section and
        marks the GUI summary as recently updated.

        Args:
            count: Current number of connected backend clients.
        """
        with self._lock:
            normalized = max(0, int(count))
            self._state.connected_clients = normalized
            self._state.gui.total_connections = normalized
            self._state.gui.last_event_wall_time = isoformat_utc_now()

    def upsert_gui_client_session(self, session: Mapping[str, Any]) -> None:
        """Insert or replace a GUI client session record.

        Missing wall-clock fields are backfilled from the best available session
        timestamp so GUI presence summaries have stable timing metadata.

        Args:
            session: GUI session payload keyed by at least ``connection_id``.

        Raises:
            ValueError: If ``connection_id`` is missing or empty.
        """
        connection_id = str(session.get("connection_id") or "").strip()
        if not connection_id:
            raise ValueError("GUI client session requires a non-empty connection_id")

        with self._lock:
            normalized = dict(session)
            wall_time = (
                normalized.get("last_message_wall_time")
                or normalized.get("last_hello_wall_time")
                or normalized.get("connected_at")
                or isoformat_utc_now()
            )
            normalized.setdefault("connected_at", wall_time)
            normalized.setdefault("last_hello_wall_time", wall_time)
            normalized.setdefault("last_message_wall_time", wall_time)
            normalized.setdefault("last_ping_wall_time", None)
            self._state.gui.by_connection_id[connection_id] = normalized
            self._state.gui.last_event_wall_time = wall_time
            self._refresh_gui_presence_locked()

    def remove_gui_client_session(self, *, connection_id: str) -> None:
        """Remove a GUI client session if it exists.

        Args:
            connection_id: Connection identifier for the session to remove.
        """
        with self._lock:
            self._state.gui.by_connection_id.pop(connection_id, None)
            self._state.gui.last_event_wall_time = isoformat_utc_now()
            self._refresh_gui_presence_locked()

    def touch_gui_client_session(
        self,
        *,
        connection_id: str,
        wall_time: str | None = None,
        message_type: str | None = None,
        is_ping: bool = False,
    ) -> None:
        """Refresh activity metadata for an existing GUI client session.

        Args:
            connection_id: Connection identifier for the session to update.
            wall_time: Event wall-clock timestamp. The current UTC time is used
                when omitted.
            message_type: Last backend message type received from the session.
            is_ping: Whether the activity should also update the last ping time.
        """
        with self._lock:
            session = self._state.gui.by_connection_id.get(connection_id)
            if session is None:
                return

            event_wall_time = wall_time or isoformat_utc_now()
            session["last_message_wall_time"] = event_wall_time
            if message_type:
                session["last_message_type"] = str(message_type)
            if is_ping:
                session["last_ping_wall_time"] = event_wall_time
            self._state.gui.last_event_wall_time = event_wall_time
            self._refresh_gui_presence_locked()

    @property
    def recording_session_consumed(self) -> bool:
        """Return whether the current recording session allowance has been used."""
        with self._lock:
            return self._state.run.recording_session_consumed

    def mark_run_started(
        self,
        *,
        run_id: str,
        mode: str,
        test_name: str,
        operator: str | None,
        profile_name: str | None,
        started_wall_time: str,
        notes: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Mark a run as started and initialize run-scoped state.

        This updates run metadata, arms the recording clock for live runs, and
        initializes playback clock state for playback runs.

        Args:
            run_id: Active run identifier.
            mode: Run mode, such as ``live`` or ``playback``.
            test_name: Human-readable test or run name.
            operator: Operator name associated with the run.
            profile_name: Active sequence or profile name.
            started_wall_time: ISO wall-clock timestamp for run start.
            notes: Optional run notes.
            metadata: Additional run metadata stored on the run snapshot.
        """
        with self._lock:
            self._state.run.active_run_id = run_id
            self._state.run.is_running = True
            self._state.run.recording_session_consumed = True
            self._state.run.mode = mode
            self._state.run.status = "running"
            self._state.run.test_name = test_name
            self._state.run.operator = operator
            self._state.run.profile_name = profile_name
            self._state.run.notes = notes
            self._state.run.metadata = dict(metadata or {})
            self._state.run.last_started_wall_time = started_wall_time
            self._state.run.last_finish_reason = None
            self._state.run.last_finished_wall_time = None

            self._state.recording_clock.active = mode == "live"
            self._state.recording_clock.status = (
                "recording" if mode == "live" else "idle"
            )
            self._state.recording_clock.started_wall_time = (
                started_wall_time if mode == "live" else None
            )
            self._state.recording_clock.stopped_wall_time = None
            self._state.recording_clock.elapsed_seconds = 0.0
            self._state.recording_clock.display_text = (
                "Recording: 0m 00s" if mode == "live" else "Not Recording"
            )
            self._state.recording_clock.accent = (
                "recording" if mode == "live" else "neutral"
            )

            if mode == "playback":
                self._state.playback_clock.active = True
                self._state.playback_clock.status = "ready"
                self._state.playback_clock.source_run_id = run_id
                self._state.playback_clock.started_wall_time = started_wall_time
                self._state.playback_clock.updated_wall_time = started_wall_time
            else:
                self._state.playback_clock.active = False
                self._state.playback_clock.status = "idle"
                self._state.playback_clock.source_run_id = None
                self._state.playback_clock.position_seconds = None
                self._state.playback_clock.total_duration_seconds = None
                self._state.playback_clock.display_text = "Playback: --"
                self._state.playback_clock.accent = "neutral"
                self._state.playback_clock.started_wall_time = None
                self._state.playback_clock.updated_wall_time = None

            self._state.sequence.profile_name = profile_name
            self._state.sequence.updated_wall_time = started_wall_time

    def mark_run_finished(
        self,
        *,
        run_id: str,
        finished_wall_time: str,
        reason: str,
    ) -> None:
        """Mark the active run as finished and finalize clock state.

        Args:
            run_id: Run identifier being marked finished.
            finished_wall_time: ISO wall-clock timestamp for run completion.
            reason: Backend finish reason recorded on the run summary.
        """
        with self._lock:
            self._state.run.active_run_id = run_id
            self._state.run.is_running = False
            self._state.run.status = "completed"
            self._state.run.archive_complete = True
            self._state.run.last_finished_wall_time = finished_wall_time
            self._state.run.last_finish_reason = reason

            started_wall_time = self._state.run.last_started_wall_time
            elapsed_seconds = self._elapsed_seconds_between(
                started_wall_time, finished_wall_time
            )
            if elapsed_seconds is not None:
                self._state.recording_clock.elapsed_seconds = elapsed_seconds

            self._state.recording_clock.active = False
            self._state.recording_clock.status = "stopped"
            self._state.recording_clock.stopped_wall_time = finished_wall_time
            self._state.recording_clock.display_text = self._format_recording_display(
                elapsed_seconds=self._state.recording_clock.elapsed_seconds,
                active=False,
            )
            self._state.recording_clock.accent = "neutral"

            self._state.playback_clock.status = (
                "stopped"
                if self._state.playback_clock.active
                else self._state.playback_clock.status
            )
            self._state.playback_clock.updated_wall_time = finished_wall_time

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
        """Update the backend bus connection summary.

        Args:
            connected: Whether the bus is currently connected.
            reconnecting: Whether the bus is currently reconnecting.
            wall_time: Wall-clock timestamp for the latest connection-state
                transition.
            sender: Optional bus sender name.
            bitrate: Optional configured bus bitrate.
            registered_ids: Optional iterable of device IDs registered on the
                bus.
            skipped_ids: Optional iterable of device IDs skipped during
                registration.
        """
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
        """Replace the exported device inventory snapshot.

        Args:
            devices: Normalized device descriptor snapshots.
            load_errors: Optional device catalog load errors to expose in the
                backend state.
        """
        with self._lock:
            self._state.device_registry.devices = [dict(device) for device in devices]
            self._state.device_registry.total_devices = len(devices)
            self._state.device_registry.load_errors = list(load_errors or [])
            self._state.device_registry.load_error_count = len(
                self._state.device_registry.load_errors
            )

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
        runtime_state: Any = None,
        runtime_position: Any = None,
        runtime_status: Any = None,
    ) -> None:
        """Record the latest packet and runtime summary for a device.

        The device runtime entry is replaced with the latest packet metadata and
        runtime fields while incrementing the packet count.

        Args:
            device_id: Device identifier.
            wall_time: ISO wall-clock timestamp for packet receipt.
            packet_id: Packet device or message identifier.
            packet_seq: Packet sequence number.
            packet_cmd: Packet command value.
            packet_reply: Whether the packet is marked as a reply.
            packet_err: Whether the packet is marked as an error.
            packet_rsvd: Whether the packet reserved bit is set.
            packet_timestamp: Optional packet timestamp from the runtime layer.
            packet_data: Raw packet payload bytes.
            runtime_value: Runtime value derived from the packet.
            runtime_aux: Auxiliary runtime value derived from the packet.
            runtime_time: Runtime time metadata derived from the packet.
            source: Runtime source label for this update.
            runtime_state: Optional normalized runtime state.
            runtime_position: Optional normalized runtime position.
            runtime_status: Optional normalized runtime status.
        """
        with self._lock:
            current = self._state.device_runtime.by_id.get(device_id, {})
            packet_count = int(current.get("packet_count", 0)) + 1

            self._state.device_runtime.by_id[device_id] = {
                "device_id": device_id,
                "online": True,
                "source": source,
                "packet_count": packet_count,
                "last_packet_wall_time": wall_time,
                "last_packet_age_seconds": 0.0,
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
                "runtime_state": runtime_state,
                "runtime_position": runtime_position,
                "runtime_status": runtime_status,
            }

    def set_mission_clock(
        self,
        *,
        seconds: float,
        state: str = "running",
        wall_time: str | None = None,
        label: str | None = None,
    ) -> None:
        """Update the mission clock snapshot.

        Args:
            seconds: Mission clock value in seconds.
            state: Mission clock state label.
            wall_time: Update timestamp. The current UTC time is used when
                omitted.
            label: Optional mission clock label override.
        """
        with self._lock:
            self._state.mission_clock.seconds = max(0.0, float(seconds))
            self._state.mission_clock.state = state
            self._state.mission_clock.updated_wall_time = (
                wall_time or isoformat_utc_now()
            )
            if label is not None:
                self._state.mission_clock.label = str(label)

    def reset_mission_clock(self, *, wall_time: str | None = None) -> None:
        """Reset the mission clock to its idle zero state.

        Args:
            wall_time: Update timestamp. The current UTC time is used when
                omitted.
        """
        with self._lock:
            self._state.mission_clock.seconds = 0.0
            self._state.mission_clock.state = "idle"
            self._state.mission_clock.updated_wall_time = (
                wall_time or isoformat_utc_now()
            )

    def set_playback_clock(
        self,
        *,
        source_run_id: str | None,
        total_duration_seconds: float | None,
        position_seconds: float | None = None,
        status: str = "ready",
        wall_time: str | None = None,
    ) -> None:
        """Update playback clock timing and status fields.

        Args:
            source_run_id: Source run identifier for the playback session, or
                None to mark playback inactive.
            total_duration_seconds: Total playback duration in seconds.
            position_seconds: Current playback position in seconds.
            status: Playback status label.
            wall_time: Update timestamp. The current UTC time is used when
                omitted.
        """
        with self._lock:
            self._state.playback_clock.active = source_run_id is not None
            self._state.playback_clock.source_run_id = source_run_id
            self._state.playback_clock.total_duration_seconds = self._normalize_seconds(
                total_duration_seconds
            )
            self._state.playback_clock.position_seconds = self._normalize_seconds(
                position_seconds
            )
            self._state.playback_clock.status = status
            self._state.playback_clock.updated_wall_time = (
                wall_time or isoformat_utc_now()
            )

    def clear_playback_clock(self, *, wall_time: str | None = None) -> None:
        """Reset playback clock fields to the idle placeholder state.

        Args:
            wall_time: Update timestamp. The current UTC time is used when
                omitted.
        """
        with self._lock:
            self._state.playback_clock.active = False
            self._state.playback_clock.status = "idle"
            self._state.playback_clock.source_run_id = None
            self._state.playback_clock.total_duration_seconds = None
            self._state.playback_clock.position_seconds = None
            self._state.playback_clock.display_text = "Playback: --"
            self._state.playback_clock.accent = "neutral"
            self._state.playback_clock.started_wall_time = None
            self._state.playback_clock.updated_wall_time = (
                wall_time or isoformat_utc_now()
            )

    def set_sequence_state(
        self,
        *,
        current_state: str | None,
        current_phase: str | None = None,
        current_step_name: str | None = None,
        current_step_index: int | None = None,
        hold_state: str | None = None,
        profile_name: str | None = None,
        details: Mapping[str, Any] | None = None,
        wall_time: str | None = None,
    ) -> None:
        """Update the exported sequence summary.

        Args:
            current_state: Current sequence state label.
            current_phase: Optional current phase label.
            current_step_name: Optional current step name.
            current_step_index: Optional current step index.
            hold_state: Optional hold-state label.
            profile_name: Optional active profile name override.
            details: Optional additional sequence details.
            wall_time: Update timestamp. The current UTC time is used when
                omitted.
        """
        with self._lock:
            self._state.sequence.current_state = current_state
            self._state.sequence.current_phase = current_phase
            self._state.sequence.current_step_name = current_step_name
            self._state.sequence.current_step_index = current_step_index
            self._state.sequence.hold_state = hold_state
            if profile_name is not None:
                self._state.sequence.profile_name = profile_name
            self._state.sequence.details = dict(details or {})
            self._state.sequence.updated_wall_time = wall_time or isoformat_utc_now()

    def set_alarm_state(
        self,
        *,
        active_alarms: Iterable[Mapping[str, Any]] | None = None,
        active_faults: Iterable[Mapping[str, Any]] | None = None,
        wall_time: str | None = None,
    ) -> None:
        """Replace the active alarm and fault summaries.

        Args:
            active_alarms: Current active alarm records.
            active_faults: Current active fault records.
            wall_time: Update timestamp. The current UTC time is used when
                omitted.
        """
        with self._lock:
            alarm_list = [dict(item) for item in list(active_alarms or [])]
            fault_list = [dict(item) for item in list(active_faults or [])]
            self._state.alarms.active_alarms = alarm_list
            self._state.alarms.active_faults = fault_list
            self._state.alarms.active_alarm_count = len(alarm_list)
            self._state.alarms.active_fault_count = len(fault_list)
            self._state.alarms.updated_wall_time = wall_time or isoformat_utc_now()

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
        is_held: bool = False,
        hold_requested: bool = False,
    ) -> None:
        """Initialize script-runner state for a newly started script.

        Args:
            script_id: Backend script identifier.
            name: Script display name.
            pid: Process ID for the running script.
            launch_mode: Script launch mode recorded by the backend.
            command: Executed command line.
            cwd: Working directory used to launch the script.
            started_wall_time: ISO wall-clock timestamp for script start.
            current_step_index: Optional current plan step index.
            total_steps: Optional total plan step count.
            current_step_name: Optional current plan step name.
            current_step_type: Optional current plan step type.
            current_step_status: Optional current plan step status.
            plan_steps_summary: Optional summary of planned script steps.
            is_held: Whether the script starts in a held state.
            hold_requested: Whether a hold has already been requested.
        """
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
            self._state.script_runner.last_failure_message = None
            self._state.script_runner.last_exit_status = None
            self._state.script_runner.output_lines = []
            self._state.script_runner.current_step_index = current_step_index
            self._state.script_runner.total_steps = total_steps
            self._state.script_runner.current_step_name = current_step_name
            self._state.script_runner.current_step_type = current_step_type
            self._state.script_runner.current_step_status = current_step_status
            self._state.script_runner.last_progress_wall_time = started_wall_time
            self._state.script_runner.plan_steps_summary = list(
                plan_steps_summary or []
            )
            self._state.script_runner.is_held = is_held
            self._state.script_runner.hold_requested = hold_requested
            self._state.script_runner.last_hold_wall_time = None
            self._state.script_runner.last_continue_wall_time = None

    def mark_script_finished(
        self,
        *,
        finished_wall_time: str,
        return_code: int | None,
        reason: str,
        failure_message: str | None = None,
        exit_status: str | None = None,
    ) -> None:
        """Record script completion metadata.

        Args:
            finished_wall_time: ISO wall-clock timestamp for script completion.
            return_code: Process exit code, when one exists.
            reason: Backend stop reason.
            failure_message: Optional failure message for unsuccessful exits.
            exit_status: Optional higher-level script exit status label.
        """
        with self._lock:
            self._state.script_runner.is_running = False
            self._state.script_runner.finished_wall_time = finished_wall_time
            self._state.script_runner.last_exit_code = return_code
            self._state.script_runner.last_stop_reason = reason
            self._state.script_runner.last_failure_message = failure_message
            self._state.script_runner.last_exit_status = exit_status

    def append_script_output(self, text: str, *, max_lines: int = 500) -> None:
        """Append a script output line and enforce the retained history cap.

        Args:
            text: Output line to append.
            max_lines: Maximum number of lines to retain in memory.
        """
        with self._lock:
            self._state.script_runner.output_lines.append(text)
            if len(self._state.script_runner.output_lines) > max_lines:
                self._state.script_runner.output_lines = (
                    self._state.script_runner.output_lines[-max_lines:]
                )

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
        is_held: bool | None = None,
        hold_requested: bool | None = None,
    ) -> None:
        """Update script progress and optional hold metadata.

        Args:
            current_step_index: Current plan step index.
            total_steps: Total number of plan steps.
            current_step_name: Current plan step name.
            current_step_type: Current plan step type.
            current_step_status: Current plan step status.
            progress_wall_time: ISO wall-clock timestamp for the progress
                update.
            plan_steps_summary: Optional replacement plan summary.
            is_held: Optional held-state override.
            hold_requested: Optional hold-requested override.
        """
        with self._lock:
            self._state.script_runner.current_step_index = current_step_index
            self._state.script_runner.total_steps = total_steps
            self._state.script_runner.current_step_name = current_step_name
            self._state.script_runner.current_step_type = current_step_type
            self._state.script_runner.current_step_status = current_step_status
            self._state.script_runner.last_progress_wall_time = progress_wall_time
            if plan_steps_summary is not None:
                self._state.script_runner.plan_steps_summary = list(plan_steps_summary)
            if is_held is not None:
                self._state.script_runner.is_held = bool(is_held)
            if hold_requested is not None:
                self._state.script_runner.hold_requested = bool(hold_requested)

    def mark_script_hold_requested(
        self,
        *,
        wall_time: str,
        current_step_index: int | None = None,
        total_steps: int | None = None,
        current_step_name: str | None = None,
        current_step_type: str | None = None,
    ) -> None:
        """Mark the running script as having a pending hold request.

        Args:
            wall_time: ISO wall-clock timestamp for the hold request.
            current_step_index: Optional current step index override.
            total_steps: Optional total step count override.
            current_step_name: Optional current step name override.
            current_step_type: Optional current step type override.
        """
        with self._lock:
            self._state.script_runner.hold_requested = True
            self._state.script_runner.current_step_status = "hold_requested"
            self._state.script_runner.last_progress_wall_time = wall_time
            if current_step_index is not None:
                self._state.script_runner.current_step_index = current_step_index
            if total_steps is not None:
                self._state.script_runner.total_steps = total_steps
            if current_step_name is not None:
                self._state.script_runner.current_step_name = current_step_name
            if current_step_type is not None:
                self._state.script_runner.current_step_type = current_step_type

    def mark_script_held(
        self,
        *,
        wall_time: str,
        current_step_index: int | None = None,
        total_steps: int | None = None,
        current_step_name: str | None = None,
        current_step_type: str | None = None,
    ) -> None:
        """Mark the running script as held.

        Args:
            wall_time: ISO wall-clock timestamp for the held transition.
            current_step_index: Optional current step index override.
            total_steps: Optional total step count override.
            current_step_name: Optional current step name override.
            current_step_type: Optional current step type override.
        """
        with self._lock:
            self._state.script_runner.is_held = True
            self._state.script_runner.hold_requested = True
            self._state.script_runner.current_step_status = "held"
            self._state.script_runner.last_hold_wall_time = wall_time
            self._state.script_runner.last_progress_wall_time = wall_time
            if current_step_index is not None:
                self._state.script_runner.current_step_index = current_step_index
            if total_steps is not None:
                self._state.script_runner.total_steps = total_steps
            if current_step_name is not None:
                self._state.script_runner.current_step_name = current_step_name
            if current_step_type is not None:
                self._state.script_runner.current_step_type = current_step_type

    def mark_script_continued(
        self,
        *,
        wall_time: str,
        current_step_index: int | None = None,
        total_steps: int | None = None,
        current_step_name: str | None = None,
        current_step_type: str | None = None,
    ) -> None:
        """Mark the running script as resumed from hold.

        Args:
            wall_time: ISO wall-clock timestamp for the continue transition.
            current_step_index: Optional current step index override.
            total_steps: Optional total step count override.
            current_step_name: Optional current step name override.
            current_step_type: Optional current step type override.
        """
        with self._lock:
            self._state.script_runner.is_held = False
            self._state.script_runner.hold_requested = False
            self._state.script_runner.current_step_status = "running"
            self._state.script_runner.last_continue_wall_time = wall_time
            self._state.script_runner.last_progress_wall_time = wall_time
            if current_step_index is not None:
                self._state.script_runner.current_step_index = current_step_index
            if total_steps is not None:
                self._state.script_runner.total_steps = total_steps
            if current_step_name is not None:
                self._state.script_runner.current_step_name = current_step_name
            if current_step_type is not None:
                self._state.script_runner.current_step_type = current_step_type

    def clear_script_running_state(self) -> None:
        """Clear the live script-runner execution fields.

        Persistent completion metadata such as the last exit code and finish
        time are left untouched.
        """
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
            self._state.script_runner.is_held = False
            self._state.script_runner.hold_requested = False
            self._state.script_runner.last_hold_wall_time = None
            self._state.script_runner.last_continue_wall_time = None

    def upsert_device_runtime_shadow(
        self,
        *,
        device_id: str,
        wall_time: str,
        source: str,
        runtime_value: Any = None,
        runtime_aux: Any = None,
        runtime_time: Any = None,
        runtime_state: Any = None,
        runtime_position: Any = None,
        runtime_status: Any = None,
        online: bool | None = None,
    ) -> None:
        """Merge runtime-only device fields into an existing device shadow.

        Unlike :meth:`mark_device_packet`, this updates runtime-derived fields
        without replacing packet metadata.

        Args:
            device_id: Device identifier.
            wall_time: ISO wall-clock timestamp for the runtime update.
            source: Runtime source label for this update.
            runtime_value: Optional runtime value.
            runtime_aux: Optional auxiliary runtime value.
            runtime_time: Optional runtime time value.
            runtime_state: Optional runtime state value.
            runtime_position: Optional runtime position value.
            runtime_status: Optional runtime status value.
            online: Optional online-state override.
        """
        with self._lock:
            current = dict(self._state.device_runtime.by_id.get(device_id, {}))
            current["device_id"] = device_id
            current["source"] = source
            current["last_runtime_update_wall_time"] = wall_time

            if online is None:
                current.setdefault("online", False)
            else:
                current["online"] = bool(online)

            if runtime_value is not None:
                current["runtime_value"] = runtime_value
            if runtime_aux is not None:
                current["runtime_aux"] = runtime_aux
            if runtime_time is not None:
                current["runtime_time"] = runtime_time
            if runtime_state is not None:
                current["runtime_state"] = runtime_state
            if runtime_position is not None:
                current["runtime_position"] = runtime_position
            if runtime_status is not None:
                current["runtime_status"] = runtime_status

            self._state.device_runtime.by_id[device_id] = current

    def mark_command_result(
        self,
        *,
        request_id: str | None,
        requested_at: str | None,
        request_source: str | None,
        authority_level: str | None,
        command_name: str | None,
        device_id: str | None,
        status: str,
        dispatched_via: str | None,
        adapter_name: str | None,
        run_mode: str | None,
        rejection_reason: str | None = None,
        interlock_reason: str | None = None,
        validation_errors: Iterable[str] | None = None,
        state_reasons: Iterable[str] | None = None,
        error: str | None = None,
        result_summary: Mapping[str, Any] | None = None,
    ) -> None:
        """Record the latest command outcome summary.

        Args:
            request_id: Command request identifier.
            requested_at: Wall-clock timestamp when the command was requested.
            request_source: Originating request source.
            authority_level: Authority level associated with the request.
            command_name: Command name.
            device_id: Target device identifier, when applicable.
            status: Backend command outcome status.
            dispatched_via: Dispatch path or adapter category.
            adapter_name: Adapter name used for the command.
            run_mode: Run mode active when the command was evaluated.
            rejection_reason: Optional rejection reason.
            interlock_reason: Optional interlock reason.
            validation_errors: Optional validation errors.
            state_reasons: Optional state-based reasons collected during
                evaluation.
            error: Optional command error text.
            result_summary: Optional structured command result summary.
        """
        with self._lock:
            self._state.last_command.request_id = request_id
            self._state.last_command.requested_at = requested_at
            self._state.last_command.request_source = request_source
            self._state.last_command.authority_level = authority_level
            self._state.last_command.command_name = command_name
            self._state.last_command.device_id = device_id
            self._state.last_command.status = str(status)
            self._state.last_command.dispatched_via = dispatched_via
            self._state.last_command.adapter_name = adapter_name
            self._state.last_command.run_mode = run_mode
            self._state.last_command.rejection_reason = rejection_reason
            self._state.last_command.interlock_reason = interlock_reason
            self._state.last_command.validation_errors = [
                str(item) for item in (validation_errors or [])
            ]
            self._state.last_command.state_reasons = [
                str(item) for item in (state_reasons or [])
            ]
            self._state.last_command.error = error
            self._state.last_command.result_summary = dict(result_summary or {})

    def set_health_snapshot(
        self,
        *,
        sampled_at: str,
        overall_status: str,
        active_warnings: list[str],
        writers: Mapping[str, Any],
        bus: Mapping[str, Any],
        script: Mapping[str, Any],
        gui: Mapping[str, Any],
    ) -> None:
        """Replace the exported backend health snapshot.

        Args:
            sampled_at: ISO wall-clock timestamp when health was sampled.
            overall_status: Aggregate backend health status.
            active_warnings: Active health warning messages.
            writers: Writer-health summary keyed by writer name.
            bus: Bus-health summary payload.
            script: Script-runner health summary payload.
            gui: GUI-health summary payload.
        """
        with self._lock:
            self._state.health.sampled_at = sampled_at
            self._state.health.overall_status = overall_status
            self._state.health.active_warnings = list(active_warnings)
            self._state.health.active_warning_count = len(active_warnings)
            self._state.health.writers = {
                str(name): dict(value) for name, value in writers.items()
            }
            self._state.health.bus = dict(bus)
            self._state.health.script = dict(script)
            self._state.health.gui = dict(gui)

    def get_snapshot(self) -> dict[str, Any]:
        """Return a deep-copied backend runtime snapshot.

        Transient fields such as packet ages and clock display text are
        refreshed before the snapshot is materialized.

        Returns:
            A deep-copied dictionary representation of the backend runtime
            state.
        """
        with self._lock:
            self._refresh_transient_fields_locked()
            return deepcopy(self._state.to_dict())

    def get_backend_status(self) -> dict[str, Any]:
        """Return the compact backend status payload used by status requests.

        Returns:
            A summary dictionary containing backend startup metadata, run state,
            clock summaries, health summary fields, and the last command
            snapshot.
        """
        with self._lock:
            self._refresh_transient_fields_locked()
            return {
                "backend_started_at": self._state.backend_started_at,
                "connected_clients": self._state.connected_clients,
                "active_run_id": self._state.run.active_run_id,
                "is_running": self._state.run.is_running,
                "run_mode": self._state.run.mode,
                "recording": {
                    "active": self._state.recording_clock.active,
                    "status": self._state.recording_clock.status,
                    "elapsed_seconds": self._state.recording_clock.elapsed_seconds,
                    "display_text": self._state.recording_clock.display_text,
                },
                "mission_clock": {
                    "state": self._state.mission_clock.state,
                    "seconds": self._state.mission_clock.seconds,
                    "label": self._state.mission_clock.label,
                },
                "playback_clock": {
                    "active": self._state.playback_clock.active,
                    "status": self._state.playback_clock.status,
                    "position_seconds": self._state.playback_clock.position_seconds,
                    "total_duration_seconds": self._state.playback_clock.total_duration_seconds,
                    "display_text": self._state.playback_clock.display_text,
                },
                "health_summary": {
                    "sampled_at": self._state.health.sampled_at,
                    "overall_status": self._state.health.overall_status,
                    "active_warning_count": self._state.health.active_warning_count,
                    "active_warnings": list(self._state.health.active_warnings),
                    "gui_status": self._state.health.gui.get("status"),
                    "gui_warning_count": self._state.health.gui.get("warning_count"),
                },
                "last_command": self._state.last_command.to_dict(),
            }

    def _refresh_transient_fields_locked(self) -> None:
        """Refresh derived fields before a snapshot is returned."""
        now_wall_time = isoformat_utc_now()
        self._refresh_gui_presence_locked()
        self._refresh_device_packet_ages_locked(now_wall_time=now_wall_time)
        self._refresh_recording_clock_locked(now_wall_time=now_wall_time)
        self._refresh_playback_clock_locked(now_wall_time=now_wall_time)

    def _refresh_gui_presence_locked(self) -> None:
        """Recompute GUI presence summaries from the tracked connection map."""
        now_wall_time = isoformat_utc_now()
        sessions = list(self._state.gui.by_connection_id.values())
        self._state.gui.total_windows = len(sessions)
        self._state.gui.total_connections = max(
            self._state.connected_clients, len(sessions)
        )
        self._state.gui.window_roles = sorted(
            {
                str(item.get("window_role"))
                for item in sessions
                if item.get("window_role") not in (None, "")
            }
        )
        self._state.gui.logical_client_ids = sorted(
            {
                str(item.get("logical_client_id"))
                for item in sessions
                if item.get("logical_client_id") not in (None, "")
            }
        )

        for session in sessions:
            age_seconds = self._elapsed_seconds_between(
                session.get("last_message_wall_time"), now_wall_time
            )
            session["last_message_age_seconds"] = age_seconds

    def _refresh_device_packet_ages_locked(self, *, now_wall_time: str) -> None:
        """Update per-device packet ages relative to the current wall time.

        Args:
            now_wall_time: ISO wall-clock timestamp used as the age reference.
        """
        for device_state in self._state.device_runtime.by_id.values():
            packet_wall_time = device_state.get("last_packet_wall_time")
            age_seconds = self._elapsed_seconds_between(packet_wall_time, now_wall_time)
            device_state["last_packet_age_seconds"] = age_seconds

    def _refresh_recording_clock_locked(self, *, now_wall_time: str) -> None:
        """Refresh derived recording clock fields.

        Args:
            now_wall_time: ISO wall-clock timestamp used as the age reference.
        """
        if (
            self._state.recording_clock.active
            and self._state.recording_clock.started_wall_time
        ):
            elapsed_seconds = self._elapsed_seconds_between(
                self._state.recording_clock.started_wall_time,
                now_wall_time,
            )
            if elapsed_seconds is not None:
                self._state.recording_clock.elapsed_seconds = elapsed_seconds

        self._state.recording_clock.display_text = self._format_recording_display(
            elapsed_seconds=self._state.recording_clock.elapsed_seconds,
            active=self._state.recording_clock.active,
        )
        self._state.recording_clock.accent = (
            "recording" if self._state.recording_clock.active else "neutral"
        )

    def _refresh_playback_clock_locked(self, *, now_wall_time: str) -> None:
        """Refresh derived playback clock fields.

        Args:
            now_wall_time: ISO wall-clock timestamp used to stamp the playback
                clock update time.
        """
        total_duration = self._state.playback_clock.total_duration_seconds
        position = self._state.playback_clock.position_seconds

        if total_duration is None and not self._state.playback_clock.active:
            self._state.playback_clock.display_text = "Playback: --"
            self._state.playback_clock.accent = "neutral"
            return

        if total_duration is None:
            self._state.playback_clock.display_text = "Duration: --"
        elif position is None:
            self._state.playback_clock.display_text = (
                f"Duration: {self._format_duration(total_duration)}"
            )
        else:
            self._state.playback_clock.display_text = f"Playback: {self._format_duration(position)} / {self._format_duration(total_duration)}"

        self._state.playback_clock.accent = (
            "playback" if self._state.playback_clock.active else "neutral"
        )
        self._state.playback_clock.updated_wall_time = now_wall_time

    def _format_recording_display(self, *, elapsed_seconds: float, active: bool) -> str:
        """Format the user-facing recording clock label.

        Args:
            elapsed_seconds: Recording duration in seconds.
            active: Whether recording is currently active.

        Returns:
            The display string for the recording clock.
        """
        if not active and elapsed_seconds <= 0.0:
            return "Not Recording"
        return f"Recording: {self._format_duration(elapsed_seconds)}"

    def _format_duration(self, seconds: float | int | None) -> str:
        """Format a duration as whole minutes and seconds.

        Args:
            seconds: Duration in seconds.

        Returns:
            A ``<minutes>m <seconds>s`` display string rounded to the nearest
            whole second and clamped to zero or above.
        """
        normalized = int(max(0, round(float(seconds or 0.0))))
        minutes, remaining_seconds = divmod(normalized, 60)
        return f"{minutes}m {remaining_seconds:02d}s"

    def _normalize_seconds(self, value: float | int | None) -> float | None:
        """Normalize a numeric duration value.

        Args:
            value: Candidate duration value.

        Returns:
            A non-negative float when the value can be parsed, or None when the
            value is missing or invalid.
        """
        if value is None:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return None

    def _elapsed_seconds_between(
        self, start_wall_time: str | None, end_wall_time: str | None
    ) -> float | None:
        """Compute the non-negative elapsed seconds between two ISO wall times.

        Args:
            start_wall_time: Start wall-clock timestamp.
            end_wall_time: End wall-clock timestamp.

        Returns:
            The elapsed seconds between the parsed timestamps, or None when
            either timestamp cannot be parsed.
        """
        start_dt = parse_iso_wall_time(start_wall_time)
        end_dt = parse_iso_wall_time(end_wall_time)
        if start_dt is None or end_dt is None:
            return None
        delta = (end_dt - start_dt).total_seconds()
        return max(0.0, delta)


def parse_iso_wall_time(value: str | None) -> datetime | None:
    """Parse an ISO wall-clock timestamp into a UTC datetime.

    The parser accepts ``Z`` suffixes and naive datetimes. Naive timestamps are
    interpreted as UTC.

    Args:
        value: ISO wall-clock timestamp string.

    Returns:
        A timezone-aware UTC datetime, or None when the value is empty or
        invalid.
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def isoformat_utc_now() -> str:
    """Return the current UTC time as an ISO string with a ``Z`` suffix.

    Returns:
        The current UTC time formatted as an ISO 8601 string.
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
