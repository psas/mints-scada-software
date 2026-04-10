# backend/run_controller.py

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from historymanager import HistoryManager
from historymanager.integrity import scan_and_write_run_integrity
from historymanager.manager import isoformat_z

from .state_store import StateStore


class RunController:
    """Coordinate backend run lifecycle, snapshots, and archive finalization.

    This controller starts and finishes recording runs through ``HistoryManager``,
    mirrors run lifecycle state into ``StateStore``, writes archive lifecycle
    events, emits numbered snapshots, and persists post-close integrity summary
    information for playback and UI consumers.
    """

    def __init__(
        self,
        *,
        history_manager: HistoryManager,
        state_store: StateStore,
    ) -> None:
        """Initialize the run lifecycle controller.

        Args:
            history_manager: History subsystem used to create runs, write
                snapshots, record lifecycle events, and finalize archives.
            state_store: Authoritative backend runtime state store updated when
                runs start and finish.
        """
        self.history_manager = history_manager
        self.state_store = state_store
        self._next_snapshot_index = 0
        self._periodic_snapshot_interval_seconds = 5.0
        self._last_periodic_snapshot_recorded_at: str | None = None

    def start_run(
        self,
        *,
        test_name: str,
        mode: str = "live",
        run_id: str | None = None,
        operator: str | None = None,
        profile_name: str | None = None,
        notes: str | None = None,
        software_git_commit: str | None = None,
        software_branch: str | None = None,
        device_map_version: str | None = None,
        svg_version: str | None = None,
        bus_config: Mapping[str, Any] | None = None,
        clock_info: Mapping[str, Any] | None = None,
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Start a run, seed lifecycle state, and write the initial snapshot.

        The start path creates the run through ``HistoryManager``, marks the run
        active in ``StateStore``, records a ``run_archive_initialized`` system
        event, and writes snapshot index ``0`` with ``recorded_at`` anchored to
        the run start wall time.

        Args:
            test_name: User-facing test name stored in run metadata.
            mode: Run mode, usually ``"live"`` or ``"playback"``.
            run_id: Optional caller-supplied run identifier.
            operator: Operator name stored with the run metadata.
            profile_name: Selected profile name stored with the run metadata.
            notes: Optional notes stored with the run metadata.
            software_git_commit: Git commit recorded in state metadata.
            software_branch: Git branch recorded in state metadata.
            device_map_version: Device map version recorded in state metadata.
            svg_version: SCADA or SVG version recorded in state metadata.
            bus_config: Bus configuration metadata copied into state metadata.
            clock_info: Clock metadata copied into state metadata.
            extra_metadata: Additional metadata copied into state metadata.

        Returns:
            A run-start summary containing the active run metadata, start wall
            time, initial snapshot path, and archive initialization status.

        Raises:
            RuntimeError: If the application already consumed its single
                recording session, or if ``HistoryManager`` does not expose the
                active run after ``start_run()`` returns.
        """
        if self.state_store.recording_session_consumed:
            raise RuntimeError(
                "Recording session already consumed - restart the application for a new run"
            )

        run_id_value = self.history_manager.start_run(
            test_name=test_name,
            mode=mode,
            run_id=run_id,
            operator=operator,
            profile_name=profile_name,
            notes=notes,
            software_git_commit=software_git_commit,
            software_branch=software_branch,
            device_map_version=device_map_version,
            svg_version=svg_version,
            bus_config=bus_config,
            clock_info=clock_info,
            extra_metadata=extra_metadata,
        )

        current_run = self.history_manager.current_run
        if current_run is None:
            raise RuntimeError(
                "HistoryManager did not expose current_run after start_run()"
            )

        state_metadata: dict[str, Any] = {
            "software_git_commit": software_git_commit,
            "software_branch": software_branch,
            "device_map_version": device_map_version,
            "svg_version": svg_version,
            "bus_config": dict(bus_config or {}),
            "clock_info": dict(clock_info or {}),
            "extra_metadata": dict(extra_metadata or {}),
        }

        self.state_store.mark_run_started(
            run_id=run_id_value,
            mode=mode,
            test_name=test_name,
            operator=operator,
            profile_name=profile_name,
            started_wall_time=current_run.started_wall_time,
            notes=notes,
            metadata=state_metadata,
        )

        self._next_snapshot_index = 0
        self._last_periodic_snapshot_recorded_at = None
        self._record_archive_lifecycle_event(
            event_type="run_archive_initialized",
            severity="info",
            run_id=run_id_value,
            mode=mode,
            test_name=test_name,
            operator=operator,
            profile_name=profile_name,
            notes=notes,
            started_wall_time=current_run.started_wall_time,
            metadata=state_metadata,
        )
        # Anchor the initial snapshot's recorded_at to the run start wall time
        # so that the snapshot file and the periodic-snapshot timer share the
        # same reference point.
        initial_snapshot = dict(self.state_store.get_snapshot())
        initial_snapshot["recorded_at"] = current_run.started_wall_time
        initial_snapshot_path = self._write_snapshot(initial_snapshot)
        self._last_periodic_snapshot_recorded_at = current_run.started_wall_time

        return {
            "run_id": run_id_value,
            "mode": mode,
            "status": "running",
            "test_name": test_name,
            "operator": operator,
            "profile_name": profile_name,
            "notes": notes,
            "started_wall_time": current_run.started_wall_time,
            "initial_snapshot_path": str(initial_snapshot_path),
            "archive_initialized": True,
        }

    def finish_run(self, *, reason: str = "operator_stop") -> dict[str, Any]:
        """Finalize the active run and persist post-close integrity summary data.

        The finish path writes a finalizing lifecycle event, writes a final
        snapshot preview, closes the archive through ``HistoryManager``, tries
        to sort the merged history, marks the run finished in ``StateStore``,
        and then attempts to write ``integrity_report.json`` without letting an
        integrity scan failure abort run shutdown.

        Args:
            reason: Caller-supplied finish reason stored in the final snapshot
                preview and returned in the finish summary.

        Returns:
            A finish summary containing final snapshot information, archive
            finalization status, merged-history sort errors, and integrity scan
            status details for the UI or launcher path.

        Raises:
            RuntimeError: If no run is currently active.
        """
        current_run = self.history_manager.current_run
        if current_run is None:
            raise RuntimeError("No active run to finish")

        run_id = current_run.run_id
        mode = current_run.metadata.get("mode")
        test_name = current_run.metadata.get("test_name")
        operator = current_run.metadata.get("operator")
        profile_name = current_run.metadata.get("profile_name")

        preview_finished_wall_time = isoformat_z()
        final_snapshot_preview = self._build_final_snapshot_preview(
            run_id=run_id,
            finished_wall_time=preview_finished_wall_time,
            reason=reason,
        )

        self._record_archive_lifecycle_event(
            event_type="run_archive_finalizing",
            severity="info",
            run_id=run_id,
            mode=mode,
            test_name=test_name,
            operator=operator,
            profile_name=profile_name,
            reason=reason,
            finished_wall_time=preview_finished_wall_time,
        )
        final_snapshot_path = self._write_snapshot(final_snapshot_preview)

        finished_run_id = self.history_manager.finish_run(reason=reason)

        merged_history_sort_error: str | None = None
        try:
            self.history_manager.sort_merged_history_for_run(finished_run_id)
        except Exception as exc:
            merged_history_sort_error = str(exc)

        self.state_store.mark_run_finished(
            run_id=finished_run_id,
            finished_wall_time=preview_finished_wall_time,
            reason=reason,
        )

        integrity_status = "unknown"
        integrity_badge = "red"
        integrity_summary_message = "Integrity scan did not run."
        integrity_report_path: str | None = None
        integrity_scan_error: str | None = None

        try:
            integrity_report, report_path = scan_and_write_run_integrity(
                finished_run_id
            )
            integrity_status = str(integrity_report.get("overall_status") or "unknown")
            integrity_badge = str(integrity_report.get("badge") or "red")
            integrity_summary_message = str(
                integrity_report.get("summary_message")
                or "Integrity scan completed, but no summary was provided."
            )
            integrity_report_path = str(report_path)
        except Exception as exc:
            integrity_scan_error = str(exc)
            integrity_summary_message = f"Integrity scan failed after run close: {exc}"

        return {
            "run_id": finished_run_id,
            "mode": mode,
            "status": "completed",
            "test_name": test_name,
            "operator": operator,
            "profile_name": profile_name,
            "reason": reason,
            "finished_wall_time": preview_finished_wall_time,
            "final_snapshot_path": str(final_snapshot_path),
            "archive_finalized": True,
            "integrity_status": integrity_status,
            "integrity_badge": integrity_badge,
            "integrity_summary_message": integrity_summary_message,
            "integrity_report_path": integrity_report_path,
            "integrity_scan_error": integrity_scan_error,
            "merged_history_sort_error": merged_history_sort_error,
        }

    def _record_archive_lifecycle_event(
        self,
        *,
        event_type: str,
        severity: str,
        **extra: Any,
    ) -> None:
        """Record matching raw and structured archive lifecycle system events.

        Args:
            event_type: Lifecycle event name such as
                ``"run_archive_initialized"`` or ``"run_archive_finalizing"``.
            severity: Severity stored on both event representations.
            **extra: Additional event fields merged into the recorded payloads.

        Returns:
            None.
        """
        if not self.history_manager.is_running:
            return

        raw_event = {
            "event_kind": "system_event",
            "event_type": event_type,
            "severity": severity,
            "recorded_by": "backend",
            "wall_time": isoformat_z(),
            **extra,
        }
        self.history_manager.record_raw_event("system_event", raw_event)

        structured_event = {
            **raw_event,
            "structured_at": isoformat_z(),
        }
        self.history_manager.record_structured_event("system_event", structured_event)

    def _write_snapshot(self, snapshot: Mapping[str, Any]) -> Any:
        """Write the next numbered snapshot and advance the local index counter.

        Args:
            snapshot: Snapshot payload to persist.

        Returns:
            The path returned by ``HistoryManager.write_snapshot``.
        """
        path = self.history_manager.write_snapshot(self._next_snapshot_index, snapshot)
        self._next_snapshot_index += 1
        return path

    def maybe_write_periodic_snapshot(
        self,
        *,
        snapshot: Mapping[str, Any],
        event_recorded_at: str | None = None,
    ) -> str | None:
        """Write a periodic snapshot when enough in-order time has elapsed.

        The snapshot timer is based on event ``recorded_at`` timestamps rather
        than wall-clock checks performed here. Out-of-order timestamps and
        timestamps inside the configured interval are skipped.

        Args:
            snapshot: Current backend snapshot candidate to persist.
            event_recorded_at: Timestamp associated with the event that may
                trigger this periodic snapshot. When absent or invalid, the
                current UTC timestamp is used.

        Returns:
            The written snapshot path as a string, or None when recording is not
            active or the timestamp does not advance the periodic snapshot
            interval.
        """
        if not self.history_manager.is_running:
            return None

        target_recorded_at = event_recorded_at or isoformat_z()
        try:
            target_dt = _parse_iso_utc(target_recorded_at)
        except ValueError:
            target_recorded_at = isoformat_z()
            target_dt = _parse_iso_utc(target_recorded_at)

        last_recorded_at = self._last_periodic_snapshot_recorded_at
        if isinstance(last_recorded_at, str):
            try:
                last_dt = _parse_iso_utc(last_recorded_at)
                delta_seconds = (target_dt - last_dt).total_seconds()
                if delta_seconds < 0:
                    # Out-of-order or older event - do not write a snapshot
                    # from a timestamp that predates the last one.
                    return None
                if delta_seconds < float(self._periodic_snapshot_interval_seconds):
                    # Not enough time has passed since last snapshot.
                    return None
            except ValueError:
                pass

        snapshot_payload = dict(snapshot)
        snapshot_payload["recorded_at"] = target_recorded_at
        snapshot_path = self._write_snapshot(snapshot_payload)
        self._last_periodic_snapshot_recorded_at = target_recorded_at
        return str(snapshot_path)

    def _build_final_snapshot_preview(
        self,
        *,
        run_id: str,
        finished_wall_time: str,
        reason: str,
    ) -> dict[str, Any]:
        """Build the final pre-close snapshot view used during run finalization.

        The preview copies the current backend snapshot and updates the run,
        recording clock, playback clock, and archive sections so the final
        snapshot reflects the completed run state before the archive is fully
        closed.

        Args:
            run_id: Run identifier being finalized.
            finished_wall_time: Wall-clock finish timestamp to embed into the
                preview state.
            reason: Finish reason stored in run and archive preview fields.

        Returns:
            A deep-copied snapshot payload updated to reflect the completed run.
        """
        snapshot = deepcopy(self.state_store.get_snapshot())

        run_state = dict(snapshot.get("run", {}))
        run_state["active_run_id"] = run_id
        run_state["is_running"] = False
        run_state["status"] = "completed"
        run_state["last_finished_wall_time"] = finished_wall_time
        run_state["last_finish_reason"] = reason
        snapshot["run"] = run_state

        started_wall_time = run_state.get("last_started_wall_time")
        elapsed_seconds = self._elapsed_seconds_between(
            started_wall_time, finished_wall_time
        )

        recording_clock = dict(snapshot.get("recording_clock", {}))
        recording_clock["active"] = False
        recording_clock["status"] = "stopped"
        recording_clock["stopped_wall_time"] = finished_wall_time
        if elapsed_seconds is not None:
            recording_clock["elapsed_seconds"] = elapsed_seconds
        recording_clock["display_text"] = self._format_recording_display(
            elapsed_seconds=recording_clock.get("elapsed_seconds"),
            active=False,
        )
        recording_clock["accent"] = "neutral"
        snapshot["recording_clock"] = recording_clock

        playback_clock = dict(snapshot.get("playback_clock", {}))
        if playback_clock.get("active"):
            playback_clock["status"] = "stopped"
        playback_clock["updated_wall_time"] = finished_wall_time
        snapshot["playback_clock"] = playback_clock

        archive_state = dict(snapshot.get("archive", {}))
        archive_state["finalized_preview"] = True
        archive_state["preview_finished_wall_time"] = finished_wall_time
        archive_state["preview_finish_reason"] = reason
        archive_state["next_snapshot_index"] = self._next_snapshot_index
        snapshot["archive"] = archive_state

        snapshot.setdefault("run_id", run_id)
        snapshot.setdefault("recorded_at", finished_wall_time)
        return snapshot

    @staticmethod
    def _elapsed_seconds_between(
        start_wall_time: Any, end_wall_time: Any
    ) -> float | None:
        """Return non-negative elapsed seconds between two ISO UTC timestamps.

        Args:
            start_wall_time: Start timestamp candidate.
            end_wall_time: End timestamp candidate.

        Returns:
            The elapsed seconds when both values are valid ISO timestamps and
            the interval is non-negative, otherwise None.
        """
        if not isinstance(start_wall_time, str) or not isinstance(end_wall_time, str):
            return None
        try:
            start_dt = _parse_iso_utc(start_wall_time)
            end_dt = _parse_iso_utc(end_wall_time)
        except ValueError:
            return None
        elapsed = (end_dt - start_dt).total_seconds()
        return elapsed if elapsed >= 0 else None

    @staticmethod
    def _format_recording_display(*, elapsed_seconds: Any, active: bool) -> str:
        """Format the recording clock label used in backend snapshot state.

        Args:
            elapsed_seconds: Elapsed recording duration in seconds.
            active: Whether the recording clock is currently active.

        Returns:
            The display string shown for the recording clock. Invalid elapsed
            values produce the placeholder active label or ``"Not Recording"``.
        """
        if not isinstance(elapsed_seconds, (int, float)):
            return "Recording: --m : --s" if active else "Not Recording"
        total_seconds = max(0, int(elapsed_seconds))
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        prefix = "Recording" if active else "Recorded"
        return f"{prefix}: {minutes:02d}m : {seconds:02d}s"


def _parse_iso_utc(value: str) -> datetime:
    """Parse an ISO timestamp string, accepting a trailing ``Z`` suffix.

    Args:
        value: ISO-formatted timestamp string.

    Returns:
        A ``datetime`` parsed from the normalized timestamp.

    Raises:
        ValueError: If the timestamp cannot be parsed by
            ``datetime.fromisoformat``.
    """
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized)
