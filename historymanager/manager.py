# historymanager/manager.py

"""History run lifecycle and archive writer coordination.

This module owns run-scoped history setup, first-order event materialization,
writer process orchestration, snapshot enqueueing, and writer health
aggregation for raw, rawbak, and structured history outputs.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import queue
import re
import threading
import time
from collections.abc import Mapping as MappingABC
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .models import (
    ActiveRun,
    FIRST_ORDER_EVENT_STREAMS,
    RAW_STREAM_FILENAMES,
    STRUCTURED_STREAM_FILENAMES,
    WriterStatsState,
)
from .paths import build_run_paths, ensure_base_dirs
from .writers import (
    WriterRuntime,
    create_raw_writer_runtime,
    create_structured_writer_runtime,
)

SHARED_EVENT_IDENTITY_FIELDS = (
    "run_id",
    "stream",
    "recorded_at",
    "event_uid",
    "stream_seq",
    "global_seq",
    "canonical_hash",
)

_CANONICAL_HASH_EXCLUDED_FIELDS = frozenset(
    {
        *SHARED_EVENT_IDENTITY_FIELDS,
        "structured_at",
    }
)


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime.

    Returns:
        The current time in UTC.
    """
    return datetime.now(timezone.utc)


def isoformat_z(dt: datetime | None = None) -> str:
    """Format a datetime as an ISO 8601 UTC timestamp with a trailing ``Z``.

    Args:
        dt: Datetime to format. When omitted, the current UTC time is used.

    Returns:
        The formatted timestamp with millisecond precision.
    """
    value = dt or utc_now()
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically replace a JSON file with a formatted mapping payload.

    The payload is written to a temporary sibling file, flushed and fsynced,
    then moved into place with ``os.replace``.

    Args:
        path: Destination JSON file path.
        payload: Mapping payload to serialize.

    Returns:
        None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def _canonicalize_for_hash(value: Any) -> Any:
    """Normalize nested values into a deterministic hashable JSON shape.

    Mappings are converted into key-sorted dictionaries with string keys, and
    tuples are normalized into lists so semantically equivalent payloads hash
    the same way.

    Args:
        value: Value to normalize.

    Returns:
        The normalized value tree.
    """
    if isinstance(value, MappingABC):
        return {
            str(key): _canonicalize_for_hash(inner_value)
            for key, inner_value in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        return [_canonicalize_for_hash(item) for item in value]
    if isinstance(value, tuple):
        return [_canonicalize_for_hash(item) for item in value]
    return value


def _touch_file(path: Path) -> None:
    """Create an empty file and its parent directory.

    Args:
        path: File path to create.

    Returns:
        None.

    Raises:
        FileExistsError: If the file already exists.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=False)


def _append_jsonl(path: Path, payload: Mapping[str, Any], *, fsync: bool) -> None:
    """Append one JSON object line to a JSONL file.

    Args:
        path: JSONL file path.
        payload: Mapping payload to serialize on one line.
        fsync: Whether to fsync the file after the append.

    Returns:
        None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=False))
        handle.write("\n")
        handle.flush()
        if fsync:
            os.fsync(handle.fileno())


def _sanitize_name(value: str) -> str:
    """Convert free-form run text into a filesystem-safe name fragment.

    Args:
        value: Input text such as a test name.

    Returns:
        A lowercase underscore-separated identifier. Returns ``"run"`` when the
        sanitized result would otherwise be empty.
    """
    cleaned = value.strip().lower().replace(" ", "_")
    cleaned = re.sub(r"[^a-z0-9_\-]+", "", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned or "run"


class HistoryManager:
    """Manage history runs, writer processes, and archive-side metadata.

    A ``HistoryManager`` owns the active run directory layout, initial metadata
    and completion markers, first-order event identity materialization, writer
    process startup and shutdown, snapshot enqueueing, and aggregated writer
    health/state for the raw, rawbak, and structured archive sides.
    """

    def __init__(
        self,
        project_root: str | Path | None = None,
        *,
        raw_queue_maxsize: int = 2000,
        raw_enqueue_timeout_s: float = 0.05,
        structured_queue_maxsize: int = 2000,
        structured_enqueue_timeout_s: float = 0.05,
        writer_start_timeout_s: float = 5.0,
        writer_finish_timeout_s: float = 5.0,
        writer_shutdown_timeout_s: float = 3.0,
        fsync_raw_writes: bool = True,
        fsync_structured_writes: bool = False,
        enable_raw_writer: bool = True,
        enable_rawbak_writer: bool = True,
        enable_structured_writer: bool = True,
    ) -> None:
        """Initialize writer settings and active-run state for history output.

        Args:
            project_root: Project root used to resolve the history base
                directories.
            raw_queue_maxsize: Maximum size for each raw-side writer command
                queue.
            raw_enqueue_timeout_s: Timeout used when enqueueing raw-side writer
                commands.
            structured_queue_maxsize: Maximum size for the structured writer
                command queue.
            structured_enqueue_timeout_s: Timeout used when enqueueing
                structured-writer commands.
            writer_start_timeout_s: Timeout for waiting on writer startup
                acknowledgements.
            writer_finish_timeout_s: Timeout for waiting on writer
                ``finish_run`` acknowledgements.
            writer_shutdown_timeout_s: Timeout for waiting on writer shutdown
                acknowledgements and joins.
            fsync_raw_writes: Whether raw-side writers fsync each event append.
            fsync_structured_writes: Whether the structured writer fsyncs each
                event append.
            enable_raw_writer: Whether to create and use the raw writer.
            enable_rawbak_writer: Whether to create and use the raw backup
                writer.
            enable_structured_writer: Whether to create and use the structured
                writer.

        Returns:
            None.
        """
        self.base_dirs = ensure_base_dirs(project_root)
        self.raw_queue_maxsize = raw_queue_maxsize
        self.raw_enqueue_timeout_s = raw_enqueue_timeout_s
        self.structured_queue_maxsize = structured_queue_maxsize
        self.structured_enqueue_timeout_s = structured_enqueue_timeout_s
        self.writer_start_timeout_s = writer_start_timeout_s
        self.writer_finish_timeout_s = writer_finish_timeout_s
        self.writer_shutdown_timeout_s = writer_shutdown_timeout_s
        self.fsync_raw_writes = fsync_raw_writes
        self.fsync_structured_writes = fsync_structured_writes

        self.enable_raw_writer = bool(enable_raw_writer)
        self.enable_rawbak_writer = bool(enable_rawbak_writer)
        self.enable_structured_writer = bool(enable_structured_writer)

        self._mp_context = mp.get_context("spawn")
        self._lock = threading.RLock()
        self.current_run: ActiveRun | None = None
        self.is_running = False
        self._raw_writer: WriterRuntime | None = None
        self._rawbak_writer: WriterRuntime | None = None
        self._structured_writer: WriterRuntime | None = None

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
        """Start a new history run and launch the configured writer processes.

        This creates the run directories, writes initial metadata and stats
        files, initializes the active run state and sequence counters, then
        starts the raw, rawbak, and structured writers that are enabled.

        Args:
            test_name: Human-readable test name used in metadata and default run
                ID generation.
            mode: Run mode recorded in metadata, such as ``"live"``.
            run_id: Explicit run identifier. When omitted, one is generated from
                the local timestamp and test name.
            operator: Operator name stored in run metadata.
            profile_name: Selected profile name stored in run metadata.
            notes: Optional free-form run notes.
            software_git_commit: Software commit identifier stored in metadata.
            software_branch: Software branch name stored in metadata.
            device_map_version: Device map version stored in metadata.
            svg_version: SCADA/SVG version stored in metadata.
            bus_config: Bus configuration metadata persisted with the run.
            clock_info: Additional clock metadata merged into the run's
                ``clock_info`` block.
            extra_metadata: Extra top-level metadata fields to merge into the
                initial metadata payload.

        Returns:
            The resolved run ID for the newly started run.

        Raises:
            RuntimeError: If another run is already active.
            Exception: Propagates writer startup failures after best-effort
                cleanup.
        """
        with self._lock:
            if self.is_running or self.current_run is not None:
                raise RuntimeError(
                    "HistoryManager.start_run() called while another run is active"
                )

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
                stream_counts={
                    **{name: 0 for name in STRUCTURED_STREAM_FILENAMES},
                    "merged": 0,
                },
            )

            self._write_initial_files(
                run_paths=run_paths,
                metadata=metadata,
                raw_stats=raw_stats,
                rawbak_stats=rawbak_stats,
                history_stats=history_stats,
            )

            run = ActiveRun(
                run_id=resolved_run_id,
                paths=run_paths,
                metadata=metadata,
                started_wall_time=started_wall_time,
                started_mono_ns=started_mono_ns,
                raw_stats=raw_stats,
                rawbak_stats=rawbak_stats,
                history_stats=history_stats,
                stream_sequence_counters={
                    stream_name: 0 for stream_name in FIRST_ORDER_EVENT_STREAMS
                },
            )

            self.current_run = run
            self.is_running = True

            try:
                self._start_writers(run)
            except Exception:
                self._best_effort_shutdown_writers(run)
                self.current_run = None
                self.is_running = False
                raise

            self._write_writer_stats_triplet(run)
            return resolved_run_id

    def finish_run(self, reason: str = "operator_stop") -> str:
        """Finish the active run and persist completion metadata.

        This drains pending writer status messages, asks all active writers to
        finish and shut down, updates the run metadata to completed, writes
        final writer stats, and writes the ``complete.json`` markers.

        Args:
            reason: Completion reason recorded in the complete payload.

        Returns:
            The finished run ID.

        Raises:
            RuntimeError: If no run is active.
        """
        with self._lock:
            run = self._require_active_run()

            self._drain_writer_status_queues(run)
            self._finish_writers(run)

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
        """Materialize and enqueue a first-order event to raw-side writers.

        The payload is normalized into the shared first-order event shape before
        enqueue. When the caller passed a mutable ``dict``, that dictionary is
        updated in place with the materialized fields so downstream callers see
        the authoritative event identity.

        Args:
            stream_name: Raw stream name to append to.
            event: First-order event payload to materialize and enqueue.

        Returns:
            None.

        Raises:
            RuntimeError: If no run is active or enqueue fails for the enabled
                raw-side writer configuration.
            ValueError: If ``stream_name`` is unknown or the event contains an
                invalid explicit sequence field.
        """
        with self._lock:
            run = self._require_active_run()
            self._validate_raw_stream(stream_name)
            self._drain_writer_status_queues(run)

            payload = self._materialize_first_order_event_payload(
                run, stream_name, event
            )

            if isinstance(event, dict):
                event.clear()
                event.update(payload)

            if not self.enable_raw_writer and not self.enable_rawbak_writer:
                return

            raw_ok = True
            rawbak_ok = True

            if self.enable_raw_writer:
                raw_ok = self._enqueue_raw_event(
                    runtime=self._raw_writer,
                    stats=run.raw_stats,
                    stream_name=stream_name,
                    payload=payload,
                )

            if self.enable_rawbak_writer:
                rawbak_ok = self._enqueue_raw_event(
                    runtime=self._rawbak_writer,
                    stats=run.rawbak_stats,
                    stream_name=stream_name,
                    payload=payload,
                )

            if not raw_ok or not rawbak_ok:
                self._write_writer_stats_triplet(run)

            if self.enable_raw_writer and self.enable_rawbak_writer:
                if not raw_ok and not rawbak_ok:
                    raise RuntimeError(
                        "record_raw_event() failed to enqueue event to both raw and rawbak writers"
                    )
            elif self.enable_raw_writer and not raw_ok:
                raise RuntimeError(
                    "record_raw_event() failed to enqueue event to raw writer"
                )
            elif self.enable_rawbak_writer and not rawbak_ok:
                raise RuntimeError(
                    "record_raw_event() failed to enqueue event to rawbak writer"
                )

    def record_structured_event(
        self,
        stream_name: str,
        event: Mapping[str, Any],
        *,
        write_merged: bool = True,
    ) -> None:
        """Materialize and enqueue a structured first-order event.

        The payload is normalized into the shared first-order event shape before
        enqueue. When ``event`` is a mutable ``dict``, it is updated in place
        with the materialized identity fields.

        Args:
            stream_name: Structured stream name to append to.
            event: Structured event payload to materialize and enqueue.
            write_merged: Whether the structured writer should also append the
                event to ``merged.jsonl``.

        Returns:
            None.

        Raises:
            RuntimeError: If no run is active, the structured writer is enabled
                but enqueue fails, or writer status indicates a failure.
            ValueError: If ``stream_name`` is unknown or the event contains an
                invalid explicit sequence field.
        """
        with self._lock:
            run = self._require_active_run()
            self._validate_structured_stream(stream_name)
            self._drain_writer_status_queues(run)

            payload = self._materialize_first_order_event_payload(
                run, stream_name, event
            )

            if isinstance(event, dict):
                event.clear()
                event.update(payload)

            if not self.enable_structured_writer:
                return

            ok = self._enqueue_structured_event(
                runtime=self._structured_writer,
                stats=run.history_stats,
                stream_name=stream_name,
                payload=payload,
                write_merged=write_merged,
            )

            if not ok:
                self._write_writer_stats_triplet(run)
                raise RuntimeError(
                    "record_structured_event() failed to enqueue structured event"
                )

    def write_snapshot(self, snapshot_index: int, snapshot: Mapping[str, Any]) -> Path:
        """Enqueue a structured snapshot for the active run.

        The snapshot payload is copied and populated with default ``run_id``,
        ``snapshot_index``, and ``recorded_at`` fields when they are missing.

        Args:
            snapshot_index: Snapshot sequence number used for the eventual
                snapshot filename.
            snapshot: Snapshot payload to enqueue.

        Returns:
            The snapshot file path that the structured writer will produce.

        Raises:
            RuntimeError: If no run is active, the structured writer is
                disabled, or snapshot enqueue fails.
        """
        with self._lock:
            run = self._require_active_run()
            self._drain_writer_status_queues(run)

            if not self.enable_structured_writer:
                raise RuntimeError(
                    "write_snapshot() called on a HistoryManager with structured writer disabled"
                )

            path = run.paths.snapshots_dir / f"{snapshot_index:06d}.json"
            payload = dict(snapshot)
            payload.setdefault("run_id", run.run_id)
            payload.setdefault("snapshot_index", snapshot_index)
            payload.setdefault("recorded_at", isoformat_z())

            ok = self._enqueue_snapshot(
                runtime=self._structured_writer,
                stats=run.history_stats,
                snapshot_index=snapshot_index,
                payload=payload,
            )

            if not ok:
                self._write_writer_stats_triplet(run)
                raise RuntimeError("write_snapshot() failed to enqueue snapshot")

            return path

    def sort_merged_history_for_run(self, run_id: str) -> str | None:
        """Sort a run's ``merged.jsonl`` by canonical playback ordering keys.

        The merged history is sorted by ``recorded_at``, then ``global_seq``,
        then ``stream_seq``, then ``event_uid`` and written back atomically.

        Args:
            run_id: Run identifier whose merged history should be rewritten.

        Returns:
            The merged history path as a string when the file exists, otherwise
            None.
        """
        run_paths = build_run_paths(run_id, self.base_dirs.project_root)
        merged_path = run_paths.merged_path
        if not merged_path.is_file():
            return None

        events: list[dict[str, Any]] = []
        with merged_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                events.append(json.loads(line))

        events.sort(
            key=lambda payload: (
                str(payload.get("recorded_at") or ""),
                (
                    int(payload.get("global_seq"))
                    if isinstance(payload.get("global_seq"), int)
                    else 0
                ),
                (
                    int(payload.get("stream_seq"))
                    if isinstance(payload.get("stream_seq"), int)
                    else 0
                ),
                str(payload.get("event_uid") or ""),
            )
        )

        temp_path = merged_path.with_name(f".{merged_path.name}.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            for payload in events:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=False))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, merged_path)
        return str(merged_path)

    def _materialize_first_order_event_payload(
        self,
        run: ActiveRun,
        stream_name: str,
        event: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Populate shared first-order event identity fields for an event.

        This method ensures the payload has canonical run and stream metadata,
        timestamps, per-stream and global sequence numbers, a stable event UID,
        and a canonical hash derived from the payload content.

        Args:
            run: Active run that owns the event.
            stream_name: Event stream name.
            event: Event payload to copy and normalize.

        Returns:
            A new dictionary containing the materialized first-order event
            payload.

        Raises:
            ValueError: If explicit ``stream_seq`` or ``global_seq`` values are
                present but invalid.
        """
        payload = dict(event)

        payload.setdefault("run_id", run.run_id)
        payload.setdefault("stream", stream_name)

        recorded_at = payload.get("recorded_at")
        if not isinstance(recorded_at, str) or not recorded_at.strip():
            payload["recorded_at"] = isoformat_z()
        else:
            payload["recorded_at"] = recorded_at.strip()

        stream_seq = payload.get("stream_seq")
        if stream_seq is None:
            payload["stream_seq"] = self._next_stream_seq(run, stream_name)
        else:
            if not isinstance(stream_seq, int) or stream_seq < 1:
                raise ValueError(
                    f"Event field 'stream_seq' must be a positive integer when provided; got {stream_seq!r}"
                )
            payload["stream_seq"] = int(stream_seq)
            self._ensure_stream_counter_floor(run, stream_name, payload["stream_seq"])

        global_seq = payload.get("global_seq")
        if global_seq is None:
            payload["global_seq"] = self._next_global_seq(run)
        else:
            if not isinstance(global_seq, int) or global_seq < 1:
                raise ValueError(
                    f"Event field 'global_seq' must be a positive integer when provided; got {global_seq!r}"
                )
            payload["global_seq"] = int(global_seq)
            self._ensure_global_sequence_floor(run, payload["global_seq"])

        event_uid = payload.get("event_uid")
        if not isinstance(event_uid, str) or not event_uid.strip():
            payload["event_uid"] = self._build_event_uid(
                run_id=run.run_id,
                stream_name=stream_name,
                stream_seq=payload["stream_seq"],
            )
        else:
            payload["event_uid"] = event_uid.strip()

        canonical_hash = payload.get("canonical_hash")
        if not isinstance(canonical_hash, str) or not canonical_hash.strip():
            payload["canonical_hash"] = self._compute_canonical_hash(payload)
        else:
            payload["canonical_hash"] = canonical_hash.strip()

        return payload

    def _next_stream_seq(self, run: ActiveRun, stream_name: str) -> int:
        """Advance and return the next per-stream sequence number.

        Args:
            run: Active run whose per-stream counter should advance.
            stream_name: Stream whose sequence counter should advance.

        Returns:
            The next positive sequence number for ``stream_name``.
        """
        if stream_name not in run.stream_sequence_counters:
            run.stream_sequence_counters[stream_name] = 0

        run.stream_sequence_counters[stream_name] += 1
        return run.stream_sequence_counters[stream_name]

    def _next_global_seq(self, run: ActiveRun) -> int:
        """Advance and return the next global event sequence number.

        Args:
            run: Active run whose global sequence counter should advance.

        Returns:
            The next positive global sequence number.
        """
        run.global_sequence_counter += 1
        return run.global_sequence_counter

    def _ensure_global_sequence_floor(self, run: ActiveRun, seq_value: int) -> None:
        """Raise the global counter floor to match an explicit event sequence.

        Args:
            run: Active run whose global sequence counter may need updating.
            seq_value: Explicit global sequence value already assigned to an
                event.

        Returns:
            None.
        """
        if seq_value > run.global_sequence_counter:
            run.global_sequence_counter = seq_value

    def _ensure_stream_counter_floor(
        self, run: ActiveRun, stream_name: str, seq_value: int
    ) -> None:
        """Raise a stream counter floor to match an explicit event sequence.

        Args:
            run: Active run whose per-stream counter may need updating.
            stream_name: Stream whose counter may need updating.
            seq_value: Explicit stream sequence value already assigned to an
                event.

        Returns:
            None.
        """
        current = run.stream_sequence_counters.get(stream_name, 0)
        if seq_value > current:
            run.stream_sequence_counters[stream_name] = seq_value

    def _build_event_uid(
        self, *, run_id: str, stream_name: str, stream_seq: int
    ) -> str:
        """Build the canonical event UID for a first-order event.

        Args:
            run_id: Owning run identifier.
            stream_name: Event stream name.
            stream_seq: Per-stream sequence number.

        Returns:
            The canonical event UID string.
        """
        return f"{run_id}:{stream_name}:{stream_seq:08d}"

    def _compute_canonical_hash(self, payload: Mapping[str, Any]) -> str:
        """Compute the canonical content hash for a first-order event payload.

        Shared identity fields and ``structured_at`` are excluded so the hash is
        stable across representations that share the same semantic content.

        Args:
            payload: Event payload to hash.

        Returns:
            The SHA-256 hex digest of the canonicalized payload.
        """
        hash_payload = {
            key: value
            for key, value in payload.items()
            if key not in _CANONICAL_HASH_EXCLUDED_FIELDS
        }
        canonical_payload = _canonicalize_for_hash(hash_payload)
        serialized = json.dumps(
            canonical_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _make_default_run_id(self, test_name: str) -> str:
        """Build the default run ID from the local timestamp and test name.

        Args:
            test_name: Test name to sanitize into the run ID suffix.

        Returns:
            The generated run ID string.
        """
        timestamp = utc_now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
        return f"{timestamp}_{_sanitize_name(test_name)}"

    def _require_active_run(self) -> ActiveRun:
        """Return the active run or raise when no run is active.

        Returns:
            The current active run.

        Raises:
            RuntimeError: If the history manager has no active run.
        """
        if not self.is_running or self.current_run is None:
            raise RuntimeError("HistoryManager has no active run")
        return self.current_run

    def _validate_raw_stream(self, stream_name: str) -> None:
        """Validate that a stream name belongs to the raw-side stream set.

        Args:
            stream_name: Stream name to validate.

        Returns:
            None.

        Raises:
            ValueError: If the stream name is unknown.
        """
        if stream_name not in RAW_STREAM_FILENAMES:
            raise ValueError(f"Unknown raw stream: {stream_name!r}")

    def _validate_structured_stream(self, stream_name: str) -> None:
        """Validate that a stream name belongs to the structured stream set.

        Args:
            stream_name: Stream name to validate.

        Returns:
            None.

        Raises:
            ValueError: If the stream name is unknown.
        """
        if stream_name not in STRUCTURED_STREAM_FILENAMES:
            raise ValueError(f"Unknown structured stream: {stream_name!r}")

    def _create_run_directories(self, run_paths) -> None:
        """Create the per-run directories needed by the enabled writers.

        Args:
            run_paths: Run path bundle returned by ``build_run_paths``.

        Returns:
            None.

        Raises:
            FileExistsError: If any enabled run directory already exists.
        """
        if self.enable_raw_writer:
            run_paths.raw_dir.mkdir(parents=True, exist_ok=False)

        if self.enable_rawbak_writer:
            run_paths.rawbak_dir.mkdir(parents=True, exist_ok=False)

        if self.enable_structured_writer:
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
        """Build the initial metadata payload written at run start.

        Args:
            run_id: Run identifier.
            test_name: Human-readable test name.
            mode: Run mode.
            started_wall_time: Run start wall-clock timestamp.
            started_mono_ns: Run start monotonic timestamp in nanoseconds.
            operator: Operator name.
            profile_name: Selected profile name.
            notes: Free-form notes.
            software_git_commit: Software commit identifier.
            software_branch: Software branch name.
            device_map_version: Device map version string.
            svg_version: SCADA/SVG version string.
            bus_config: Bus configuration metadata.
            clock_info: Additional clock metadata to merge into the canonical
                ``clock_info`` block.
            extra_metadata: Additional top-level metadata fields.

        Returns:
            The initial run metadata dictionary.
        """
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
        """Write initial metadata, stats files, and empty stream artifacts.

        Args:
            run_paths: Run path bundle for the active run.
            metadata: Initial metadata payload.
            raw_stats: Initial raw writer stats state.
            rawbak_stats: Initial raw backup writer stats state.
            history_stats: Initial structured writer stats state.

        Returns:
            None.
        """
        self._write_metadata_triplet(run_paths, metadata)

        if self.enable_raw_writer:
            atomic_write_json(run_paths.raw_writer_stats_path, raw_stats.to_dict())
            for path in run_paths.raw_stream_paths.values():
                _touch_file(path)

        if self.enable_rawbak_writer:
            atomic_write_json(
                run_paths.rawbak_writer_stats_path, rawbak_stats.to_dict()
            )
            for path in run_paths.rawbak_stream_paths.values():
                _touch_file(path)

        if self.enable_structured_writer:
            atomic_write_json(
                run_paths.history_writer_stats_path, history_stats.to_dict()
            )
            for path in run_paths.structured_stream_paths.values():
                _touch_file(path)
            _touch_file(run_paths.merged_path)

    def _write_metadata_triplet(self, run_paths, metadata: Mapping[str, Any]) -> None:
        """Write metadata.json to each enabled archive side.

        Args:
            run_paths: Run path bundle for the target run.
            metadata: Metadata payload to write.

        Returns:
            None.
        """
        if self.enable_raw_writer:
            atomic_write_json(run_paths.raw_metadata_path, metadata)

        if self.enable_rawbak_writer:
            atomic_write_json(run_paths.rawbak_metadata_path, metadata)

        if self.enable_structured_writer:
            atomic_write_json(run_paths.history_metadata_path, metadata)

    def _write_complete_triplet(self, run_paths, payload: Mapping[str, Any]) -> None:
        """Write complete.json to each enabled archive side.

        Args:
            run_paths: Run path bundle for the target run.
            payload: Completion payload to write.

        Returns:
            None.
        """
        if self.enable_raw_writer:
            atomic_write_json(run_paths.raw_complete_path, payload)

        if self.enable_rawbak_writer:
            atomic_write_json(run_paths.rawbak_complete_path, payload)

        if self.enable_structured_writer:
            atomic_write_json(run_paths.history_complete_path, payload)

    def _write_writer_stats_triplet(self, run: ActiveRun) -> None:
        """Write the current writer stats files for the active run.

        Args:
            run: Active run whose writer stats should be persisted.

        Returns:
            None.
        """
        if self.enable_raw_writer:
            atomic_write_json(run.paths.raw_writer_stats_path, run.raw_stats.to_dict())

        if self.enable_rawbak_writer:
            atomic_write_json(
                run.paths.rawbak_writer_stats_path,
                run.rawbak_stats.to_dict(),
            )

        if self.enable_structured_writer:
            atomic_write_json(
                run.paths.history_writer_stats_path,
                run.history_stats.to_dict(),
            )

    def _start_writers(self, run: ActiveRun) -> None:
        """Start each enabled writer process and wait for startup acknowledgements.

        Args:
            run: Active run whose paths and stats should be bound to the
                writer runtimes.

        Returns:
            None.

        Raises:
            TimeoutError: If a writer does not acknowledge startup in time.
            RuntimeError: If a writer reports an error during startup.
        """
        if self.enable_raw_writer:
            self._raw_writer = create_raw_writer_runtime(
                mp_context=self._mp_context,
                side_name="raw",
                queue_maxsize=self.raw_queue_maxsize,
                fsync_every_event=self.fsync_raw_writes,
            )
            self._raw_writer.process.start()
            self._raw_writer.command_queue.put(
                {
                    "type": "start_run",
                    "run_id": run.run_id,
                    "stream_paths": {
                        name: str(path)
                        for name, path in run.paths.raw_stream_paths.items()
                    },
                }
            )
            self._wait_for_expected_status(
                runtime=self._raw_writer,
                stats=run.raw_stats,
                expected_type="started",
                timeout_s=self.writer_start_timeout_s,
            )

        if self.enable_rawbak_writer:
            self._rawbak_writer = create_raw_writer_runtime(
                mp_context=self._mp_context,
                side_name="rawbak",
                queue_maxsize=self.raw_queue_maxsize,
                fsync_every_event=self.fsync_raw_writes,
            )
            self._rawbak_writer.process.start()
            self._rawbak_writer.command_queue.put(
                {
                    "type": "start_run",
                    "run_id": run.run_id,
                    "stream_paths": {
                        name: str(path)
                        for name, path in run.paths.rawbak_stream_paths.items()
                    },
                }
            )
            self._wait_for_expected_status(
                runtime=self._rawbak_writer,
                stats=run.rawbak_stats,
                expected_type="started",
                timeout_s=self.writer_start_timeout_s,
            )

        if self.enable_structured_writer:
            self._structured_writer = create_structured_writer_runtime(
                mp_context=self._mp_context,
                side_name="structured",
                queue_maxsize=self.structured_queue_maxsize,
                fsync_every_event=self.fsync_structured_writes,
            )
            self._structured_writer.process.start()
            self._structured_writer.command_queue.put(
                {
                    "type": "start_run",
                    "run_id": run.run_id,
                    "stream_paths": {
                        name: str(path)
                        for name, path in run.paths.structured_stream_paths.items()
                    },
                    "merged_path": str(run.paths.merged_path),
                    "snapshots_dir": str(run.paths.snapshots_dir),
                }
            )
            self._wait_for_expected_status(
                runtime=self._structured_writer,
                stats=run.history_stats,
                expected_type="started",
                timeout_s=self.writer_start_timeout_s,
            )

    def _enqueue_raw_event(
        self,
        *,
        runtime: WriterRuntime | None,
        stats: WriterStatsState,
        stream_name: str,
        payload: Mapping[str, Any],
    ) -> bool:
        """Enqueue a raw-side event and update writer stats.

        Args:
            runtime: Target writer runtime.
            stats: Writer stats state to update.
            stream_name: Raw stream name being written.
            payload: Materialized event payload.

        Returns:
            True when the event was enqueued, otherwise False.
        """
        now = isoformat_z()

        if runtime is None:
            stats.dropped_events += 1
            stats.add_error(wall_time=now, message="writer runtime is missing")
            return False

        if not runtime.process.is_alive():
            stats.dropped_events += 1
            stats.add_error(
                wall_time=now,
                message=f"{runtime.side_name} writer process is not alive",
            )
            return False

        try:
            runtime.command_queue.put(
                {
                    "type": "event",
                    "stream_name": stream_name,
                    "event": dict(payload),
                },
                timeout=self.raw_enqueue_timeout_s,
            )
            stats.bump_stream(stream_name)
            stats.set_status("running", pid=runtime.process.pid)
            stats.update_queue_max_depth(self._safe_queue_depth(runtime.command_queue))
            return True

        except queue.Full:
            stats.dropped_events += 1
            stats.add_error(
                wall_time=now,
                message=f"{runtime.side_name} writer queue is full",
            )
            return False

        except Exception as exc:
            stats.dropped_events += 1
            stats.add_error(
                wall_time=now,
                message=f"{runtime.side_name} enqueue failed: {exc}",
            )
            return False

    def _enqueue_structured_event(
        self,
        *,
        runtime: WriterRuntime | None,
        stats: WriterStatsState,
        stream_name: str,
        payload: Mapping[str, Any],
        write_merged: bool,
    ) -> bool:
        """Enqueue a structured event and update structured writer stats.

        Args:
            runtime: Structured writer runtime.
            stats: Structured writer stats state to update.
            stream_name: Structured stream name being written.
            payload: Materialized event payload.
            write_merged: Whether the event should also be written to the merged
                stream.

        Returns:
            True when the event was enqueued, otherwise False.
        """
        now = isoformat_z()

        if runtime is None:
            stats.dropped_events += 1
            stats.add_error(
                wall_time=now, message="structured writer runtime is missing"
            )
            return False

        if not runtime.process.is_alive():
            stats.dropped_events += 1
            stats.add_error(
                wall_time=now,
                message=f"{runtime.side_name} writer process is not alive",
            )
            return False

        try:
            runtime.command_queue.put(
                {
                    "type": "event",
                    "stream_name": stream_name,
                    "event": dict(payload),
                    "write_merged": bool(write_merged),
                },
                timeout=self.structured_enqueue_timeout_s,
            )
            stats.bump_stream(stream_name)
            if write_merged:
                stats.bump_stream("merged")
            stats.set_status("running", pid=runtime.process.pid)
            stats.update_queue_max_depth(self._safe_queue_depth(runtime.command_queue))
            return True

        except queue.Full:
            stats.dropped_events += 1
            stats.add_error(
                wall_time=now,
                message=f"{runtime.side_name} writer queue is full",
            )
            return False

        except Exception as exc:
            stats.dropped_events += 1
            stats.add_error(
                wall_time=now,
                message=f"{runtime.side_name} enqueue failed: {exc}",
            )
            return False

    def _enqueue_snapshot(
        self,
        *,
        runtime: WriterRuntime | None,
        stats: WriterStatsState,
        snapshot_index: int,
        payload: Mapping[str, Any],
    ) -> bool:
        """Enqueue a snapshot write request and update structured stats.

        Args:
            runtime: Structured writer runtime.
            stats: Structured writer stats state to update.
            snapshot_index: Snapshot sequence number.
            payload: Snapshot payload.

        Returns:
            True when the snapshot request was enqueued, otherwise False.
        """
        now = isoformat_z()

        if runtime is None:
            stats.dropped_events += 1
            stats.add_error(
                wall_time=now, message="structured writer runtime is missing"
            )
            return False

        if not runtime.process.is_alive():
            stats.dropped_events += 1
            stats.add_error(
                wall_time=now,
                message=f"{runtime.side_name} writer process is not alive",
            )
            return False

        try:
            runtime.command_queue.put(
                {
                    "type": "snapshot",
                    "snapshot_index": snapshot_index,
                    "snapshot": dict(payload),
                },
                timeout=self.structured_enqueue_timeout_s,
            )
            stats.snapshots_written += 1
            stats.set_status("running", pid=runtime.process.pid)
            stats.update_queue_max_depth(self._safe_queue_depth(runtime.command_queue))
            return True

        except queue.Full:
            stats.dropped_events += 1
            stats.add_error(
                wall_time=now,
                message=f"{runtime.side_name} writer queue is full",
            )
            return False

        except Exception as exc:
            stats.dropped_events += 1
            stats.add_error(
                wall_time=now,
                message=f"{runtime.side_name} enqueue failed: {exc}",
            )
            return False

    def _finish_writers(self, run: ActiveRun) -> None:
        """Finish, shut down, and join all active writer processes.

        Each active writer receives ``finish_run`` followed by ``shutdown`` when
        possible. If a process does not exit in time, it is force-terminated
        and the failure is recorded in writer stats.

        Args:
            run: Active run whose writer stats should be updated.

        Returns:
            None.
        """
        for runtime, stats, timeout_s in (
            (self._raw_writer, run.raw_stats, self.raw_enqueue_timeout_s),
            (self._rawbak_writer, run.rawbak_stats, self.raw_enqueue_timeout_s),
            (
                self._structured_writer,
                run.history_stats,
                self.structured_enqueue_timeout_s,
            ),
        ):
            if runtime is None:
                continue

            finish_wall_time = isoformat_z()

            if runtime.process.is_alive():
                try:
                    runtime.command_queue.put(
                        {
                            "type": "finish_run",
                            "wall_time": finish_wall_time,
                        },
                        timeout=timeout_s,
                    )
                    self._wait_for_expected_status(
                        runtime=runtime,
                        stats=stats,
                        expected_type="finished",
                        timeout_s=self.writer_finish_timeout_s,
                    )
                except Exception as exc:
                    stats.add_error(
                        wall_time=isoformat_z(),
                        message=f"{runtime.side_name} finish_run failed: {exc}",
                    )

                try:
                    if runtime.process.is_alive():
                        runtime.command_queue.put(
                            {"type": "shutdown"},
                            timeout=timeout_s,
                        )
                        self._wait_for_expected_status(
                            runtime=runtime,
                            stats=stats,
                            expected_type="shutdown_ack",
                            timeout_s=self.writer_shutdown_timeout_s,
                        )
                except Exception as exc:
                    stats.add_error(
                        wall_time=isoformat_z(),
                        message=f"{runtime.side_name} shutdown failed: {exc}",
                    )

                runtime.process.join(timeout=self.writer_shutdown_timeout_s)
                if runtime.process.is_alive():
                    runtime.process.terminate()
                    runtime.process.join(timeout=1.0)
                    stats.add_error(
                        wall_time=isoformat_z(),
                        message=f"{runtime.side_name} writer process was terminated after timeout",
                    )
                    stats.set_status("terminated", pid=runtime.process.pid)
                else:
                    stats.set_status("stopped", pid=runtime.process.pid)

            else:
                stats.add_error(
                    wall_time=isoformat_z(),
                    message=f"{runtime.side_name} writer process was already dead during finish_run",
                )

        self._raw_writer = None
        self._rawbak_writer = None
        self._structured_writer = None

    def _best_effort_shutdown_writers(self, run: ActiveRun) -> None:
        """Attempt emergency writer shutdown after startup failure.

        This path sends ``shutdown`` when possible, force-terminates still-live
        processes, clears runtime handles, and persists the resulting writer
        stats.

        Args:
            run: Active run whose writer stats should capture the cleanup
                outcome.

        Returns:
            None.
        """
        for runtime, stats in (
            (self._raw_writer, run.raw_stats),
            (self._rawbak_writer, run.rawbak_stats),
            (self._structured_writer, run.history_stats),
        ):
            if runtime is None:
                continue

            try:
                if runtime.process.is_alive():
                    try:
                        runtime.command_queue.put_nowait({"type": "shutdown"})
                    except Exception:
                        pass

                    runtime.process.join(timeout=1.0)
                    if runtime.process.is_alive():
                        runtime.process.terminate()
                        runtime.process.join(timeout=1.0)
                        stats.add_error(
                            wall_time=isoformat_z(),
                            message=f"{runtime.side_name} writer required forced termination during startup cleanup",
                        )
            finally:
                pass

        self._raw_writer = None
        self._rawbak_writer = None
        self._structured_writer = None
        self._write_writer_stats_triplet(run)

    def _wait_for_expected_status(
        self,
        *,
        runtime: WriterRuntime,
        stats: WriterStatsState,
        expected_type: str,
        timeout_s: float,
    ) -> dict[str, Any]:
        """Wait for a specific writer status message and apply interim updates.

        Args:
            runtime: Writer runtime whose status queue should be read.
            stats: Writer stats state to update with all received status
                messages.
            expected_type: Status message type to wait for.
            timeout_s: Maximum wait time in seconds.

        Returns:
            The received status message as a plain dictionary.

        Raises:
            TimeoutError: If the expected status message is not received before
                the deadline.
            RuntimeError: If the writer reports an error while waiting.
        """
        deadline = time.monotonic() + timeout_s

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Timed out waiting for {expected_type!r} from {runtime.side_name} writer"
                )

            try:
                message = runtime.status_queue.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError(
                    f"Timed out waiting for {expected_type!r} from {runtime.side_name} writer"
                ) from None

            self._apply_writer_status_message(stats, message)

            if message["type"] == "error":
                raise RuntimeError(
                    f"{runtime.side_name} writer error during {expected_type} wait: {message.get('message')}"
                )

            if message["type"] == expected_type:
                return dict(message)

    def _drain_writer_status_queues(self, run: ActiveRun) -> None:
        """Drain all pending writer status messages into the run's stats state.

        Args:
            run: Active run whose writer stats should be updated.

        Returns:
            None.
        """
        for runtime, stats in (
            (self._raw_writer, run.raw_stats),
            (self._rawbak_writer, run.rawbak_stats),
            (self._structured_writer, run.history_stats),
        ):
            if runtime is None:
                continue

            while True:
                try:
                    message = runtime.status_queue.get_nowait()
                except queue.Empty:
                    break
                else:
                    self._apply_writer_status_message(stats, message)

    def _apply_writer_status_message(
        self,
        stats: WriterStatsState,
        message: Mapping[str, Any],
    ) -> None:
        """Fold one writer status message into a ``WriterStatsState``.

        Args:
            stats: Writer stats state to update.
            message: Status message emitted by a writer runtime.

        Returns:
            None.
        """
        message_type = message["type"]
        wall_time = message.get("wall_time") or isoformat_z()
        pid = message.get("pid")

        if message_type == "started":
            stats.set_status("running", pid=pid)

        elif message_type == "flushed":
            stats.mark_flush(wall_time)
            stats.set_status("running", pid=pid)

        elif message_type == "finished":
            stats.mark_flush(wall_time)
            stats.set_status("finished", pid=pid)

        elif message_type == "snapshot_written":
            stats.mark_flush(wall_time)
            stats.set_status("running", pid=pid)

        elif message_type == "shutdown_ack":
            stats.set_status("stopped", pid=pid)

        elif message_type == "error":
            detail = message.get("message", "unknown writer error")
            command_type = message.get("command_type")
            if command_type:
                detail = f"{detail} (command_type={command_type})"
            stats.add_error(wall_time=wall_time, message=detail)

    def get_health_snapshot(self) -> dict[str, Any]:
        """Return a point-in-time health summary for all writer sides.

        Pending writer status messages are drained first so the snapshot reflects
        the latest known writer state.

        Returns:
            A health snapshot containing the sampled time, active run ID, and
            per-writer health summaries.
        """
        with self._lock:
            run = self.current_run
            if run is not None:
                self._drain_writer_status_queues(run)

            return {
                "sampled_at": isoformat_z(),
                "active_run_id": run.run_id if run is not None else None,
                "writers": {
                    "raw": self._build_writer_health_snapshot(
                        runtime=self._raw_writer,
                        stats=run.raw_stats if run is not None else None,
                        side_name="raw",
                        queue_limit=self.raw_queue_maxsize,
                    ),
                    "rawbak": self._build_writer_health_snapshot(
                        runtime=self._rawbak_writer,
                        stats=run.rawbak_stats if run is not None else None,
                        side_name="rawbak",
                        queue_limit=self.raw_queue_maxsize,
                    ),
                    "structured": self._build_writer_health_snapshot(
                        runtime=self._structured_writer,
                        stats=run.history_stats if run is not None else None,
                        side_name="structured",
                        queue_limit=self.structured_queue_maxsize,
                    ),
                },
            }

    def _build_writer_health_snapshot(
        self,
        *,
        runtime: WriterRuntime | None,
        stats: WriterStatsState | None,
        side_name: str,
        queue_limit: int,
    ) -> dict[str, Any]:
        """Build the health summary payload for one writer side.

        Args:
            runtime: Writer runtime for the side, if configured.
            stats: Current writer stats state for the side, if a run is active.
            side_name: Writer side name such as ``"raw"``.
            queue_limit: Configured command queue limit for the side.

        Returns:
            A health summary dictionary for the requested writer side.
        """
        queue_depth = (
            self._safe_queue_depth(runtime.command_queue)
            if runtime is not None
            else None
        )
        process_alive = bool(runtime is not None and runtime.process.is_alive())
        pid = runtime.process.pid if runtime is not None else None

        if stats is None:
            return {
                "side_name": side_name,
                "configured": False,
                "process_alive": process_alive,
                "pid": pid,
                "writer_status": "idle",
                "queue_depth": queue_depth,
                "queue_limit": queue_limit,
                "queue_max_depth": 0,
                "dropped_events": 0,
                "flush_count": 0,
                "last_flush_wall_time": None,
                "last_error_wall_time": None,
                "error_count": 0,
                "snapshots_written": 0,
                "stream_counts": {},
            }

        return {
            "side_name": side_name,
            "configured": runtime is not None,
            "process_alive": process_alive,
            "pid": pid or stats.writer_pid,
            "writer_status": stats.writer_status,
            "queue_depth": queue_depth,
            "queue_limit": queue_limit,
            "queue_max_depth": stats.queue_max_depth,
            "dropped_events": stats.dropped_events,
            "flush_count": stats.flush_count,
            "last_flush_wall_time": stats.last_flush_wall_time,
            "last_error_wall_time": stats.last_error_wall_time,
            "error_count": len(stats.errors),
            "snapshots_written": stats.snapshots_written,
            "stream_counts": dict(stats.stream_counts),
        }

    def _safe_queue_depth(self, queue_obj: Any) -> int | None:
        """Best-effort queue depth lookup for multiprocessing queues.

        Args:
            queue_obj: Queue-like object to inspect.

        Returns:
            The queue size when supported, otherwise None.
        """
        try:
            return int(queue_obj.qsize())
        except (NotImplementedError, AttributeError, OSError):
            return None
