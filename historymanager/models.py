from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RAW_STREAM_FILENAMES: dict[str, str] = {
    "telemetry_in": "telemetry_in.raw.jsonl",
    "wire_command_out": "wire_command_out.raw.jsonl",
    "operator_action": "operator_action.jsonl",
    "system_event": "system_event.jsonl",
}

STRUCTURED_STREAM_FILENAMES: dict[str, str] = {
    "telemetry_in": "telemetry_in.jsonl",
    "command_out": "command_out.jsonl",
    "operator_action": "operator_action.jsonl",
    "system_event": "system_event.jsonl",
}

# Streams that appear in both raw and structured archives (used for identity
# alignment and cross-archive integrity).  wire_command_out (raw) and
# command_out (structured) are intentionally separate - they record different
# data and are not cross-comparable.
SHARED_STREAM_NAMES: tuple[str, ...] = (
    "telemetry_in",
    "operator_action",
    "system_event",
)

FIRST_ORDER_EVENT_STREAMS: tuple[str, ...] = tuple(
    sorted(set(RAW_STREAM_FILENAMES.keys()) | set(STRUCTURED_STREAM_FILENAMES.keys()))
)

MERGED_FILENAME = "merged.jsonl"
SNAPSHOTS_DIRNAME = "snapshots"
METADATA_FILENAME = "metadata.json"
WRITER_STATS_FILENAME = "writer_stats.json"
COMPLETE_FILENAME = "complete.json"


@dataclass(frozen=True)
class BaseDirs:
    project_root: Path
    raw_root: Path
    rawbak_root: Path
    history_root: Path


@dataclass(frozen=True)
class RunPaths:
    run_id: str
    raw_dir: Path
    rawbak_dir: Path
    history_dir: Path
    snapshots_dir: Path

    @property
    def raw_metadata_path(self) -> Path:
        return self.raw_dir / METADATA_FILENAME

    @property
    def rawbak_metadata_path(self) -> Path:
        return self.rawbak_dir / METADATA_FILENAME

    @property
    def history_metadata_path(self) -> Path:
        return self.history_dir / METADATA_FILENAME

    @property
    def raw_writer_stats_path(self) -> Path:
        return self.raw_dir / WRITER_STATS_FILENAME

    @property
    def rawbak_writer_stats_path(self) -> Path:
        return self.rawbak_dir / WRITER_STATS_FILENAME

    @property
    def history_writer_stats_path(self) -> Path:
        return self.history_dir / WRITER_STATS_FILENAME

    @property
    def raw_complete_path(self) -> Path:
        return self.raw_dir / COMPLETE_FILENAME

    @property
    def rawbak_complete_path(self) -> Path:
        return self.rawbak_dir / COMPLETE_FILENAME

    @property
    def history_complete_path(self) -> Path:
        return self.history_dir / COMPLETE_FILENAME

    @property
    def raw_stream_paths(self) -> dict[str, Path]:
        return {
            stream_name: self.raw_dir / filename
            for stream_name, filename in RAW_STREAM_FILENAMES.items()
        }

    @property
    def rawbak_stream_paths(self) -> dict[str, Path]:
        return {
            stream_name: self.rawbak_dir / filename
            for stream_name, filename in RAW_STREAM_FILENAMES.items()
        }

    @property
    def structured_stream_paths(self) -> dict[str, Path]:
        return {
            stream_name: self.history_dir / filename
            for stream_name, filename in STRUCTURED_STREAM_FILENAMES.items()
        }

    @property
    def merged_path(self) -> Path:
        return self.history_dir / MERGED_FILENAME


@dataclass
class WriterStatsState:
    side_name: str
    stream_counts: dict[str, int]
    queue_max_depth: int = 0
    dropped_events: int = 0
    flush_count: int = 0
    last_flush_wall_time: str | None = None
    last_error_wall_time: str | None = None
    writer_status: str = "ready"
    writer_pid: int | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
    snapshots_written: int = 0

    def bump_stream(self, stream_name: str) -> None:
        self.stream_counts[stream_name] = self.stream_counts.get(stream_name, 0) + 1

    def update_queue_max_depth(self, depth: int | None) -> None:
        if depth is None:
            return
        if depth > self.queue_max_depth:
            self.queue_max_depth = depth

    def add_error(self, *, wall_time: str, message: str) -> None:
        self.last_error_wall_time = wall_time
        self.writer_status = "error"
        self.errors.append(
            {
                "time": wall_time,
                "message": message,
            }
        )

    def mark_flush(self, wall_time: str) -> None:
        self.flush_count += 1
        self.last_flush_wall_time = wall_time

    def set_status(self, status: str, *, pid: int | None = None) -> None:
        self.writer_status = status
        if pid is not None:
            self.writer_pid = pid

    def to_dict(self) -> dict[str, Any]:
        return {
            "side_name": self.side_name,
            "stream_counts": dict(self.stream_counts),
            "queue_max_depth": self.queue_max_depth,
            "dropped_events": self.dropped_events,
            "flush_count": self.flush_count,
            "last_flush_wall_time": self.last_flush_wall_time,
            "last_error_wall_time": self.last_error_wall_time,
            "writer_status": self.writer_status,
            "writer_pid": self.writer_pid,
            "errors": list(self.errors),
            "snapshots_written": self.snapshots_written,
        }


@dataclass
class ActiveRun:
    run_id: str
    paths: RunPaths
    metadata: dict[str, Any]
    started_wall_time: str
    started_mono_ns: int | None
    raw_stats: WriterStatsState
    rawbak_stats: WriterStatsState
    history_stats: WriterStatsState
    stream_sequence_counters: dict[str, int] = field(default_factory=dict)