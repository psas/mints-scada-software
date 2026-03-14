from __future__ import annotations

from typing import Any, Mapping

from historymanager import HistoryManager
from historymanager.manager import isoformat_z

from .state_store import StateStore


class RunController:
    """Coordinate backend run lifecycle with HistoryManager and StateStore."""

    def __init__(
        self,
        *,
        history_manager: HistoryManager,
        state_store: StateStore,
    ) -> None:
        self.history_manager = history_manager
        self.state_store = state_store

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

        self.state_store.mark_run_started(
            run_id=run_id_value,
            mode=mode,
            test_name=test_name,
            operator=operator,
            profile_name=profile_name,
            started_wall_time=current_run.started_wall_time,
        )

        return {
            "run_id": run_id_value,
            "mode": mode,
            "status": "running",
            "test_name": test_name,
            "operator": operator,
            "profile_name": profile_name,
            "started_wall_time": current_run.started_wall_time,
        }

    def finish_run(self, *, reason: str = "operator_stop") -> dict[str, Any]:
        current_run = self.history_manager.current_run
        if current_run is None:
            raise RuntimeError("No active run to finish")

        run_id = current_run.run_id
        mode = current_run.metadata.get("mode")
        test_name = current_run.metadata.get("test_name")

        finished_run_id = self.history_manager.finish_run(reason=reason)
        finished_wall_time = isoformat_z()

        self.state_store.mark_run_finished(
            run_id=finished_run_id,
            finished_wall_time=finished_wall_time,
            reason=reason,
        )

        return {
            "run_id": finished_run_id,
            "mode": mode,
            "status": "completed",
            "test_name": test_name,
            "reason": reason,
            "finished_wall_time": finished_wall_time,
        }
