"""historymanager/models.py

Shared path and state models for history archives and writer runtime state.

This module defines canonical filenames, stream-name groupings, per-run path
containers, and mutable writer statistics objects used by the history manager
and writer processes.

``SHARED_STREAM_NAMES`` lists streams that appear in both raw and structured
archives (used for identity alignment and cross-archive integrity).
``wire_command_out`` (raw) and ``command_out`` (structured) are intentionally
separate — they record different data and are not cross-comparable.
"""

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
    """Base archive roots derived from the project root.

    Attributes:
        project_root: Repository or runtime project root used to resolve
            archive directories.
        raw_root: Root directory for first-order raw archives.
        rawbak_root: Root directory for backup raw archives.
        history_root: Root directory for structured history archives.
    """

    project_root: Path
    raw_root: Path
    rawbak_root: Path
    history_root: Path


@dataclass(frozen=True)
class RunPaths:
    """Canonical filesystem paths for a single recorded run.

    Attributes:
        run_id: Stable identifier for the run directory set.
        raw_dir: Raw archive directory for the run.
        rawbak_dir: Backup raw archive directory for the run.
        history_dir: Structured history directory for the run.
        snapshots_dir: Snapshot directory inside the structured history tree.
    """

    run_id: str
    raw_dir: Path
    rawbak_dir: Path
    history_dir: Path
    snapshots_dir: Path

    @property
    def raw_metadata_path(self) -> Path:
        """Return the raw archive metadata file path.

        Returns:
            Path to ``metadata.json`` inside the raw archive directory.
        """
        return self.raw_dir / METADATA_FILENAME

    @property
    def rawbak_metadata_path(self) -> Path:
        """Return the raw backup archive metadata file path.

        Returns:
            Path to ``metadata.json`` inside the raw backup archive directory.
        """
        return self.rawbak_dir / METADATA_FILENAME

    @property
    def history_metadata_path(self) -> Path:
        """Return the structured history metadata file path.

        Returns:
            Path to ``metadata.json`` inside the structured history directory.
        """
        return self.history_dir / METADATA_FILENAME

    @property
    def raw_writer_stats_path(self) -> Path:
        """Return the raw writer statistics file path.

        Returns:
            Path to ``writer_stats.json`` inside the raw archive directory.
        """
        return self.raw_dir / WRITER_STATS_FILENAME

    @property
    def rawbak_writer_stats_path(self) -> Path:
        """Return the raw backup writer statistics file path.

        Returns:
            Path to ``writer_stats.json`` inside the raw backup archive
            directory.
        """
        return self.rawbak_dir / WRITER_STATS_FILENAME

    @property
    def history_writer_stats_path(self) -> Path:
        """Return the structured history writer statistics file path.

        Returns:
            Path to ``writer_stats.json`` inside the structured history
            directory.
        """
        return self.history_dir / WRITER_STATS_FILENAME

    @property
    def raw_complete_path(self) -> Path:
        """Return the raw archive completion marker path.

        Returns:
            Path to ``complete.json`` inside the raw archive directory.
        """
        return self.raw_dir / COMPLETE_FILENAME

    @property
    def rawbak_complete_path(self) -> Path:
        """Return the raw backup archive completion marker path.

        Returns:
            Path to ``complete.json`` inside the raw backup archive directory.
        """
        return self.rawbak_dir / COMPLETE_FILENAME

    @property
    def history_complete_path(self) -> Path:
        """Return the structured history completion marker path.

        Returns:
            Path to ``complete.json`` inside the structured history directory.
        """
        return self.history_dir / COMPLETE_FILENAME

    @property
    def raw_stream_paths(self) -> dict[str, Path]:
        """Return canonical raw stream file paths keyed by stream name.

        Returns:
            Mapping from raw stream name to the corresponding file path inside
            the raw archive directory.
        """
        return {
            stream_name: self.raw_dir / filename
            for stream_name, filename in RAW_STREAM_FILENAMES.items()
        }

    @property
    def rawbak_stream_paths(self) -> dict[str, Path]:
        """Return canonical raw backup stream file paths keyed by stream name.

        Returns:
            Mapping from raw stream name to the corresponding file path inside
            the raw backup archive directory.
        """
        return {
            stream_name: self.rawbak_dir / filename
            for stream_name, filename in RAW_STREAM_FILENAMES.items()
        }

    @property
    def structured_stream_paths(self) -> dict[str, Path]:
        """Return canonical structured stream file paths keyed by stream name.

        Returns:
            Mapping from structured stream name to the corresponding file path
            inside the structured history directory.
        """
        return {
            stream_name: self.history_dir / filename
            for stream_name, filename in STRUCTURED_STREAM_FILENAMES.items()
        }

    @property
    def merged_path(self) -> Path:
        """Return the merged structured-event stream path.

        Returns:
            Path to ``merged.jsonl`` inside the structured history directory.
        """
        return self.history_dir / MERGED_FILENAME


@dataclass
class WriterStatsState:
    """Mutable writer-side statistics accumulated during an active run.

    Attributes:
        side_name: Logical writer side name such as raw, rawbak, or history.
        stream_counts: Per-stream event counts recorded by this writer side.
        queue_max_depth: Largest observed queue depth reported for the writer.
        dropped_events: Number of events dropped before persistence.
        flush_count: Number of flush operations performed by the writer.
        last_flush_wall_time: Wall-clock timestamp of the most recent flush.
        last_error_wall_time: Wall-clock timestamp of the most recent writer
            error.
        writer_status: Current writer runtime status string.
        writer_pid: Process identifier of the writer process when known.
        errors: Collected writer error records.
        snapshots_written: Number of snapshots written by this writer side.
    """

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
        """Increment the recorded count for a stream.

        Args:
            stream_name: Stream name whose event count should be increased.

        Returns:
            None.
        """
        self.stream_counts[stream_name] = self.stream_counts.get(stream_name, 0) + 1

    def update_queue_max_depth(self, depth: int | None) -> None:
        """Record a new maximum queue depth when it exceeds the current peak.

        Args:
            depth: Newly observed queue depth, or None when no depth was
                reported.

        Returns:
            None.
        """
        if depth is None:
            return
        if depth > self.queue_max_depth:
            self.queue_max_depth = depth

    def add_error(self, *, wall_time: str, message: str) -> None:
        """Append a writer error record and mark the writer status as error.

        Args:
            wall_time: Wall-clock timestamp associated with the error.
            message: Error message recorded for the writer.

        Returns:
            None.
        """
        self.last_error_wall_time = wall_time
        self.writer_status = "error"
        self.errors.append(
            {
                "time": wall_time,
                "message": message,
            }
        )

    def mark_flush(self, wall_time: str) -> None:
        """Record a completed flush operation.

        Args:
            wall_time: Wall-clock timestamp of the flush.

        Returns:
            None.
        """
        self.flush_count += 1
        self.last_flush_wall_time = wall_time

    def set_status(self, status: str, *, pid: int | None = None) -> None:
        """Update the current writer status and optional process identifier.

        Args:
            status: New writer status string.
            pid: Writer process identifier when available.

        Returns:
            None.
        """
        self.writer_status = status
        if pid is not None:
            self.writer_pid = pid

    def to_dict(self) -> dict[str, Any]:
        """Serialize the current writer statistics state.

        Returns:
            A JSON-friendly dictionary copy of the current writer statistics,
            including stream counts and accumulated errors.
        """
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
    """Mutable runtime state for a run that is currently being recorded.

    Attributes:
        run_id: Stable identifier for the active run.
        paths: Canonical filesystem paths for the run's raw, backup, and
            structured archives.
        metadata: Run metadata written into archive metadata files.
        started_wall_time: Wall-clock time when the run started.
        started_mono_ns: Monotonic start time in nanoseconds when captured.
        raw_stats: Statistics for the raw writer side.
        rawbak_stats: Statistics for the backup raw writer side.
        history_stats: Statistics for the structured history writer side.
        stream_sequence_counters: Per-stream sequence counters used while
            assigning event identities.
        global_sequence_counter: Global event sequence counter for the active
            run.
    """

    run_id: str
    paths: RunPaths
    metadata: dict[str, Any]
    started_wall_time: str
    started_mono_ns: int | None
    raw_stats: WriterStatsState
    rawbak_stats: WriterStatsState
    history_stats: WriterStatsState
    stream_sequence_counters: dict[str, int] = field(default_factory=dict)
    global_sequence_counter: int = 0
