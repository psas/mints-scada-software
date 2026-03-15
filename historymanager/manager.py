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
from .writers import WriterRuntime, create_raw_writer_runtime

SHARED_EVENT_IDENTITY_FIELDS = (
    "run_id",
    "stream",
    "recorded_at",
    "event_uid",
    "stream_seq",
    "canonical_hash",
)

_CANONICAL_HASH_EXCLUDED_FIELDS = frozenset(
    {
        *SHARED_EVENT_IDENTITY_FIELDS,
        "structured_at",
    }
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_z(dt: datetime | None = None) -> str:
    value = dt or utc_now()
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def _canonicalize_for_hash(value: Any) -> Any:
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=False)


def _append_jsonl(path: Path, payload: Mapping[str, Any], *, fsync: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=False))
        handle.write("\n")
        handle.flush()
        if fsync:
            os.fsync(handle.fileno())


def _sanitize_name(value: str) -> str:
    cleaned = value.strip().lower().replace(" ", "_")
    cleaned = re.sub(r"[^a-z0-9_\-]+", "", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned or "run"


class HistoryManager:
    """Manage history run directories and run lifecycle."""

    def __init__(
        self,
        project_root: str | Path | None = None,
        *,
        raw_queue_maxsize: int = 2000,
        raw_enqueue_timeout_s: float = 0.05,
        writer_start_timeout_s: float = 5.0,
        writer_finish_timeout_s: float = 5.0,
        writer_shutdown_timeout_s: float = 3.0,
        fsync_raw_writes: bool = True,
        fsync_structured_writes: bool = False,
    ) -> None:
        self.base_dirs = ensure_base_dirs(project_root)

        self.raw_queue_maxsize = raw_queue_maxsize
        self.raw_enqueue_timeout_s = raw_enqueue_timeout_s
        self.writer_start_timeout_s = writer_start_timeout_s
        self.writer_finish_timeout_s = writer_finish_timeout_s
        self.writer_shutdown_timeout_s = writer_shutdown_timeout_s
        self.fsync_raw_writes = fsync_raw_writes
        self.fsync_structured_writes = fsync_structured_writes

        self._mp_context = mp.get_context("spawn")
        self._lock = threading.RLock()

        self.current_run: ActiveRun | None = None
        self.is_running = False

        self._raw_writer: WriterRuntime | None = None
        self._rawbak_writer: WriterRuntime | None = None

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
                self._start_raw_writers(run)
            except Exception:
                self._best_effort_shutdown_writers(run)
                self.current_run = None
                self.is_running = False
                raise

            self._write_writer_stats_triplet(run)
            return resolved_run_id

    def finish_run(self, reason: str = "operator_stop") -> str:
        with self._lock:
            run = self._require_active_run()

            self._drain_writer_status_queues(run)
            self._finish_raw_writers(run)

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

            raw_ok = self._enqueue_raw_event(
                runtime=self._raw_writer,
                stats=run.raw_stats,
                stream_name=stream_name,
                payload=payload,
            )
            rawbak_ok = self._enqueue_raw_event(
                runtime=self._rawbak_writer,
                stats=run.rawbak_stats,
                stream_name=stream_name,
                payload=payload,
            )

            if not raw_ok or not rawbak_ok:
                self._write_writer_stats_triplet(run)

            if not raw_ok and not rawbak_ok:
                raise RuntimeError(
                    "record_raw_event() failed to enqueue event to both raw and rawbak writers"
                )

    def record_structured_event(
        self,
        stream_name: str,
        event: Mapping[str, Any],
        *,
        write_merged: bool = True,
    ) -> None:
        with self._lock:
            run = self._require_active_run()
            self._validate_structured_stream(stream_name)

            payload = self._materialize_first_order_event_payload(
                run, stream_name, event
            )

            if isinstance(event, dict):
                event.clear()
                event.update(payload)

            _append_jsonl(
                run.paths.structured_stream_paths[stream_name],
                payload,
                fsync=self.fsync_structured_writes,
            )

            run.history_stats.bump_stream(stream_name)
            run.history_stats.mark_flush(payload["recorded_at"])

            if write_merged:
                _append_jsonl(
                    run.paths.merged_path,
                    payload,
                    fsync=self.fsync_structured_writes,
                )
                run.history_stats.bump_stream("merged")
                run.history_stats.mark_flush(payload["recorded_at"])

            self._write_writer_stats_triplet(run)

    def write_snapshot(self, snapshot_index: int, snapshot: Mapping[str, Any]) -> Path:
        with self._lock:
            run = self._require_active_run()

            path = run.paths.snapshots_dir / f"{snapshot_index:06d}.json"
            payload = dict(snapshot)
            payload.setdefault("run_id", run.run_id)
            payload.setdefault("snapshot_index", snapshot_index)
            payload.setdefault("recorded_at", isoformat_z())

            atomic_write_json(path, payload)

            run.history_stats.snapshots_written += 1
            run.history_stats.mark_flush(payload["recorded_at"])
            self._write_writer_stats_triplet(run)

            return path

    def _materialize_first_order_event_payload(
        self,
        run: ActiveRun,
        stream_name: str,
        event: Mapping[str, Any],
    ) -> dict[str, Any]:
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
        if stream_name not in run.stream_sequence_counters:
            run.stream_sequence_counters[stream_name] = 0

        run.stream_sequence_counters[stream_name] += 1
        return run.stream_sequence_counters[stream_name]

    def _ensure_stream_counter_floor(
        self, run: ActiveRun, stream_name: str, seq_value: int
    ) -> None:
        current = run.stream_sequence_counters.get(stream_name, 0)
        if seq_value > current:
            run.stream_sequence_counters[stream_name] = seq_value

    def _build_event_uid(
        self, *, run_id: str, stream_name: str, stream_seq: int
    ) -> str:
        return f"{run_id}:{stream_name}:{stream_seq:08d}"

    def _compute_canonical_hash(self, payload: Mapping[str, Any]) -> str:
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
        atomic_write_json(
            run.paths.rawbak_writer_stats_path, run.rawbak_stats.to_dict()
        )
        atomic_write_json(
            run.paths.history_writer_stats_path, run.history_stats.to_dict()
        )

    def _start_raw_writers(self, run: ActiveRun) -> None:
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
                    name: str(path) for name, path in run.paths.raw_stream_paths.items()
                },
            }
        )
        self._wait_for_expected_status(
            runtime=self._raw_writer,
            stats=run.raw_stats,
            expected_type="started",
            timeout_s=self.writer_start_timeout_s,
        )

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

    def _enqueue_raw_event(
        self,
        *,
        runtime: WriterRuntime | None,
        stats: WriterStatsState,
        stream_name: str,
        payload: Mapping[str, Any],
    ) -> bool:
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

    def _finish_raw_writers(self, run: ActiveRun) -> None:
        for runtime, stats in (
            (self._raw_writer, run.raw_stats),
            (self._rawbak_writer, run.rawbak_stats),
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
                        timeout=self.raw_enqueue_timeout_s,
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
                            timeout=self.raw_enqueue_timeout_s,
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

    def _best_effort_shutdown_writers(self, run: ActiveRun) -> None:
        for runtime, stats in (
            (self._raw_writer, run.raw_stats),
            (self._rawbak_writer, run.rawbak_stats),
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
        self._write_writer_stats_triplet(run)

    def _wait_for_expected_status(
        self,
        *,
        runtime: WriterRuntime,
        stats: WriterStatsState,
        expected_type: str,
        timeout_s: float,
    ) -> dict[str, Any]:
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
        for runtime, stats in (
            (self._raw_writer, run.raw_stats),
            (self._rawbak_writer, run.rawbak_stats),
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

        elif message_type == "shutdown_ack":
            stats.set_status("stopped", pid=pid)

        elif message_type == "error":
            detail = message.get("message", "unknown writer error")
            command_type = message.get("command_type")
            if command_type:
                detail = f"{detail} (command_type={command_type})"
            stats.add_error(wall_time=wall_time, message=detail)

    def _safe_queue_depth(self, queue_obj: Any) -> int | None:
        try:
            return int(queue_obj.qsize())
        except (NotImplementedError, AttributeError, OSError):
            return None
