from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .models import (
    ActiveRun,
    RAW_STREAM_FILENAMES,
    STRUCTURED_STREAM_FILENAMES,
    WriterStatsState,
)
from .paths import build_run_paths, ensure_base_dirs


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_z(dt: datetime | None = None) -> str:
    value = dt or utc_now()
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write JSON atomically using a temp file + replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")

    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())

    temp_path.replace(path)


def _touch_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=False)


def _sanitize_name(value: str) -> str:
    cleaned = value.strip().lower().replace(" ", "_")
    cleaned = re.sub(r"[^a-z0-9_\-]+", "", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned or "run"


class HistoryManager:
    """Manage history run directories and run lifecycle.

    This commit intentionally keeps scope narrow:
    - ensure base history root directories exist
    - create run-scoped directory trees and base files
    - manage start_run() / finish_run()

    Later commits can replace the internals of event writing with queues and
    dedicated writer processes without changing the public API shape.
    """

    def __init__(self, project_root: str | Path | None = None) -> None:
        self.base_dirs = ensure_base_dirs(project_root)

        self._lock = threading.RLock()
        self.current_run: ActiveRun | None = None
        self.is_running = False

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
    ) -> str:
        with self._lock:
            if self.is_running or self.current_run is not None:
                raise RuntimeError("HistoryManager.start_run() called while another run is active")

            resolved_run_id = run_id or self._make_default_run_id(test_name)
            run_paths = build_run_paths(resolved_run_id, self.base_dirs.project_root)

            self._create_run_directories(run_paths)

            started_wall_time = isoformat_z()
            started_mono_ns = time.monotonic_ns()

            metadata = self._build_initial_metadata(
                run_id=resolved_run_id,
                test_name=test_name,
                mode=mode,
                started_wall_time=started_wall_time,
                started_mono_ns=started_mono_ns,
                operator=operator,
                profile_name=profile_name,
                notes=notes,
                software_git_commit=software_git_commit,
                software_branch=software_branch,
                device_map_version=device_map_version,
                svg_version=svg_version,
                bus_config=dict(bus_config or {}),
                clock_info=dict(clock_info or {}),
                extra_metadata=dict(extra_metadata or {}),
            )

            raw_stats = WriterStatsState(
                side_name="raw",
                stream_counts={name: 0 for name in RAW_STREAM_FILENAMES},
            )
            rawbak_stats = WriterStatsState(
                side_name="rawbak",
                stream_counts={name: 0 for name in RAW_STREAM_FILENAMES},
            )
            history_stats = WriterStatsState(
                side_name="structured",
                stream_counts={**{name: 0 for name in STRUCTURED_STREAM_FILENAMES}, "merged": 0},
            )

            self._write_initial_files(
                run_paths=run_paths,
                metadata=metadata,
                raw_stats=raw_stats,
                rawbak_stats=rawbak_stats,
                history_stats=history_stats,
            )

            self.current_run = ActiveRun(
                run_id=resolved_run_id,
                paths=run_paths,
                metadata=metadata,
                started_wall_time=started_wall_time,
                started_mono_ns=started_mono_ns,
                raw_stats=raw_stats,
                rawbak_stats=rawbak_stats,
                history_stats=history_stats,
            )
            self.is_running = True
            return resolved_run_id

    def finish_run(self, reason: str = "operator_stop") -> str:
        with self._lock:
            run = self._require_active_run()

            end_wall_time = isoformat_z()
            end_mono_ns = time.monotonic_ns()

            run.metadata["status"] = "completed"
            run.metadata["end_wall_time"] = end_wall_time
            run.metadata.setdefault("clock_info", {})["end_wall_time"] = end_wall_time
            run.metadata.setdefault("clock_info", {})["end_mono_ns"] = end_mono_ns

            self._write_metadata_triplet(run.paths, run.metadata)
            self._write_writer_stats_triplet(run)

            complete_payload = {
                "run_id": run.run_id,
                "completed": True,
                "reason": reason,
                "end_wall_time": end_wall_time,
                "end_mono_ns": end_mono_ns,
            }
            self._write_complete_triplet(run.paths, complete_payload)

            finished_run_id = run.run_id
            self.current_run = None
            self.is_running = False
            return finished_run_id

    def record_raw_event(self, stream_name: str, event: Mapping[str, Any]) -> None:
        """Placeholder API for later writer-process integration."""
        self._validate_raw_stream(stream_name)
        self._require_active_run()
        raise NotImplementedError(
            "record_raw_event() will be implemented in the next commit with isolated writer paths"
        )

    def record_structured_event(self, stream_name: str, event: Mapping[str, Any]) -> None:
        """Placeholder API for later structured writer integration."""
        self._validate_structured_stream(stream_name)
        self._require_active_run()
        raise NotImplementedError(
            "record_structured_event() will be implemented in a later commit"
        )

    def write_snapshot(self, snapshot_index: int, snapshot: Mapping[str, Any]) -> Path:
        """Placeholder API for later snapshot writing."""
        self._require_active_run()
        raise NotImplementedError(
            "write_snapshot() will be implemented in a later commit"
        )

    def _make_default_run_id(self, test_name: str) -> str:
        timestamp = utc_now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
        return f"{timestamp}_{_sanitize_name(test_name)}"

    def _require_active_run(self) -> ActiveRun:
        if not self.is_running or self.current_run is None:
            raise RuntimeError("HistoryManager has no active run")
        return self.current_run

    def _validate_raw_stream(self, stream_name: str) -> None:
        if stream_name not in RAW_STREAM_FILENAMES:
            raise ValueError(f"Unknown raw stream: {stream_name!r}")

    def _validate_structured_stream(self, stream_name: str) -> None:
        if stream_name not in STRUCTURED_STREAM_FILENAMES:
            raise ValueError(f"Unknown structured stream: {stream_name!r}")

    def _create_run_directories(self, run_paths) -> None:
        run_paths.raw_dir.mkdir(parents=True, exist_ok=False)
        run_paths.rawbak_dir.mkdir(parents=True, exist_ok=False)
        run_paths.history_dir.mkdir(parents=True, exist_ok=False)
        run_paths.snapshots_dir.mkdir(parents=True, exist_ok=False)

    def _build_initial_metadata(
        self,
        *,
        run_id: str,
        test_name: str,
        mode: str,
        started_wall_time: str,
        started_mono_ns: int | None,
        operator: str | None,
        profile_name: str | None,
        notes: str | None,
        software_git_commit: str | None,
        software_branch: str | None,
        device_map_version: str | None,
        svg_version: str | None,
        bus_config: dict[str, Any],
        clock_info: dict[str, Any],
        extra_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "run_id": run_id,
            "test_name": test_name,
            "mode": mode,
            "status": "running",
            "start_wall_time": started_wall_time,
            "end_wall_time": None,
            "timezone": str(datetime.now().astimezone().tzinfo),
            "operator": operator,
            "profile_name": profile_name,
            "notes": notes,
            "software_git_commit": software_git_commit,
            "software_branch": software_branch,
            "device_map_version": device_map_version,
            "svg_version": svg_version,
            "bus_config": bus_config,
            "clock_info": {
                "start_wall_time": started_wall_time,
                "start_mono_ns": started_mono_ns,
                **clock_info,
            },
        }
        metadata.update(extra_metadata)
        return metadata

    def _write_initial_files(
        self,
        *,
        run_paths,
        metadata: Mapping[str, Any],
        raw_stats: WriterStatsState,
        rawbak_stats: WriterStatsState,
        history_stats: WriterStatsState,
    ) -> None:
        self._write_metadata_triplet(run_paths, metadata)

        atomic_write_json(run_paths.raw_writer_stats_path, raw_stats.to_dict())
        atomic_write_json(run_paths.rawbak_writer_stats_path, rawbak_stats.to_dict())
        atomic_write_json(run_paths.history_writer_stats_path, history_stats.to_dict())

        for path in run_paths.raw_stream_paths.values():
            _touch_file(path)

        for path in run_paths.rawbak_stream_paths.values():
            _touch_file(path)

        for path in run_paths.structured_stream_paths.values():
            _touch_file(path)

        _touch_file(run_paths.merged_path)

    def _write_metadata_triplet(self, run_paths, metadata: Mapping[str, Any]) -> None:
        atomic_write_json(run_paths.raw_metadata_path, metadata)
        atomic_write_json(run_paths.rawbak_metadata_path, metadata)
        atomic_write_json(run_paths.history_metadata_path, metadata)

    def _write_complete_triplet(self, run_paths, payload: Mapping[str, Any]) -> None:
        atomic_write_json(run_paths.raw_complete_path, payload)
        atomic_write_json(run_paths.rawbak_complete_path, payload)
        atomic_write_json(run_paths.history_complete_path, payload)

    def _write_writer_stats_triplet(self, run: ActiveRun) -> None:
        atomic_write_json(run.paths.raw_writer_stats_path, run.raw_stats.to_dict())
        atomic_write_json(run.paths.rawbak_writer_stats_path, run.rawbak_stats.to_dict())
        atomic_write_json(run.paths.history_writer_stats_path, run.history_stats.to_dict())