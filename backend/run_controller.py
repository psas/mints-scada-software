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
    """Coordinate backend run lifecycle with HistoryManager and StateStore.

    Commit 51 focus:
    - preserve the commit 50 archive lifecycle anchors and snapshots
    - persist a finished-run integrity report immediately after archive close
    - surface integrity summary information to the launcher/UI path that requested finish_run

    This lets playback catalog code load a stable ``integrity_report.json`` without
    always rescanning the archive inline, and it keeps archive finalization resilient:
    an integrity scan failure should not make run shutdown fail.
    """

    def __init__(
        self,
        *,
        history_manager: HistoryManager,
        state_store: StateStore,
    ) -> None:
        self.history_manager = history_manager
        self.state_store = state_store
        self._next_snapshot_index = 0

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
            raise RuntimeError("HistoryManager did not expose current_run after start_run()")

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
        initial_snapshot_path = self._write_snapshot(self.state_store.get_snapshot())

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
            integrity_report, report_path = scan_and_write_run_integrity(finished_run_id)
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
        }

    def _record_archive_lifecycle_event(
        self,
        *,
        event_type: str,
        severity: str,
        **extra: Any,
    ) -> None:
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
        path = self.history_manager.write_snapshot(self._next_snapshot_index, snapshot)
        self._next_snapshot_index += 1
        return path

    def _build_final_snapshot_preview(
        self,
        *,
        run_id: str,
        finished_wall_time: str,
        reason: str,
    ) -> dict[str, Any]:
        snapshot = deepcopy(self.state_store.get_snapshot())

        run_state = dict(snapshot.get("run", {}))
        run_state["active_run_id"] = run_id
        run_state["is_running"] = False
        run_state["status"] = "completed"
        run_state["last_finished_wall_time"] = finished_wall_time
        run_state["last_finish_reason"] = reason
        snapshot["run"] = run_state

        started_wall_time = run_state.get("last_started_wall_time")
        elapsed_seconds = self._elapsed_seconds_between(started_wall_time, finished_wall_time)

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
    def _elapsed_seconds_between(start_wall_time: Any, end_wall_time: Any) -> float | None:
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
        if not isinstance(elapsed_seconds, (int, float)):
            return "Recording: --m : --s" if active else "Not Recording"
        total_seconds = max(0, int(elapsed_seconds))
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        prefix = "Recording" if active else "Recorded"
        return f"{prefix}: {minutes:02d}m : {seconds:02d}s"


def _parse_iso_utc(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized)
