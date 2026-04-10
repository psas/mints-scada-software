# historymanager/writers.py

"""Worker-process entrypoints for raw and structured history writers.

This module builds the multiprocessing runtimes used by ``HistoryManager`` and
implements the long-lived worker loops that persist raw-side streams,
structured-side streams, merged structured events, and playback snapshots.
"""

from __future__ import annotations

import json
import os
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass
class WriterRuntime:
    """Own the queues and process for a single history writer worker.

    Attributes:
        side_name: Logical writer side name such as ``raw`` or ``structured``.
        command_queue: Queue used to send lifecycle and write commands to the
            worker process.
        status_queue: Queue used by the worker process to publish status and
            error messages back to the parent.
        process: Multiprocessing process object for the writer worker.
    """

    side_name: str
    command_queue: Any
    status_queue: Any
    process: Any


def create_raw_writer_runtime(
    *,
    mp_context: Any,
    side_name: str,
    queue_maxsize: int,
    fsync_every_event: bool,
) -> WriterRuntime:
    """Create the runtime wrapper for a raw-side history writer process.

    Args:
        mp_context: Multiprocessing context used to create queues and the
            writer process.
        side_name: Logical name reported in process and status metadata.
        queue_maxsize: Maximum size for the command queue.
        fsync_every_event: Whether the worker should fsync after each appended
            event.

    Returns:
        A ``WriterRuntime`` containing the raw-side writer queues and process.
    """
    command_queue = mp_context.Queue(maxsize=queue_maxsize)
    status_queue = mp_context.Queue()
    process = mp_context.Process(
        target=raw_side_writer_main,
        name=f"history-{side_name}-writer",
        args=(side_name, command_queue, status_queue, fsync_every_event),
        daemon=True,
    )
    return WriterRuntime(
        side_name=side_name,
        command_queue=command_queue,
        status_queue=status_queue,
        process=process,
    )


def create_structured_writer_runtime(
    *,
    mp_context: Any,
    side_name: str,
    queue_maxsize: int,
    fsync_every_event: bool,
) -> WriterRuntime:
    """Create the runtime wrapper for a structured-side history writer process.

    Args:
        mp_context: Multiprocessing context used to create queues and the
            writer process.
        side_name: Logical name reported in process and status metadata.
        queue_maxsize: Maximum size for the command queue.
        fsync_every_event: Whether the worker should fsync after each appended
            event.

    Returns:
        A ``WriterRuntime`` containing the structured-side writer queues and
        process.
    """
    command_queue = mp_context.Queue(maxsize=queue_maxsize)
    status_queue = mp_context.Queue()
    process = mp_context.Process(
        target=structured_side_writer_main,
        name=f"history-{side_name}-writer",
        args=(side_name, command_queue, status_queue, fsync_every_event),
        daemon=True,
    )
    return WriterRuntime(
        side_name=side_name,
        command_queue=command_queue,
        status_queue=status_queue,
        process=process,
    )


def _append_jsonl(
    handle: Any, payload: Mapping[str, Any], *, fsync_every_event: bool
) -> None:
    """Append one JSON object as a single JSONL record.

    Args:
        handle: Open text file handle to write to.
        payload: Mapping to serialize as one JSON line.
        fsync_every_event: Whether to call ``os.fsync()`` after flushing the
            appended line.

    Returns:
        None.
    """
    handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=False))
    handle.write("\n")
    handle.flush()
    if fsync_every_event:
        os.fsync(handle.fileno())


def raw_side_writer_main(
    side_name: str,
    command_queue: Any,
    status_queue: Any,
    fsync_every_event: bool,
) -> None:
    """Run the raw-side writer worker loop.

    The raw-side worker appends first-order event streams to the per-stream
    JSONL files opened for the active run. It responds to lifecycle commands
    from the parent process and publishes status or error payloads through the
    status queue.

    Args:
        side_name: Logical writer side name reported in status messages.
        command_queue: Queue that supplies lifecycle and event commands.
        status_queue: Queue used to publish worker status and error payloads.
        fsync_every_event: Whether to fsync each file after individual event
            writes and flush operations.

    Returns:
        None.
    """
    handles: dict[str, Any] = {}
    current_run_id: str | None = None

    def put_status(payload: Mapping[str, Any]) -> None:
        """Publish a status payload to the parent process.

        Args:
            payload: Status mapping to copy onto the status queue.

        Returns:
            None.
        """
        status_queue.put(dict(payload))

    def flush_handles() -> None:
        """Flush all open raw-side stream handles.

        Returns:
            None.
        """
        for handle in handles.values():
            handle.flush()
            if fsync_every_event:
                os.fsync(handle.fileno())

    def close_handles() -> None:
        """Flush and close all open raw-side stream handles.

        Returns:
            None.
        """
        nonlocal handles
        for handle in handles.values():
            try:
                handle.flush()
                if fsync_every_event:
                    os.fsync(handle.fileno())
            finally:
                handle.close()
        handles = {}

    while True:
        message = command_queue.get()
        message_type = message["type"]

        try:
            if message_type == "start_run":
                stream_paths = message["stream_paths"]
                current_run_id = message["run_id"]
                handles = {
                    stream_name: Path(path_str).open("a", encoding="utf-8")
                    for stream_name, path_str in stream_paths.items()
                }
                put_status(
                    {
                        "type": "started",
                        "side_name": side_name,
                        "run_id": current_run_id,
                        "pid": os.getpid(),
                    }
                )

            elif message_type == "event":
                if not handles:
                    raise RuntimeError(
                        f"{side_name} writer received event before start_run"
                    )
                stream_name = message["stream_name"]
                payload = message["event"]
                handle = handles[stream_name]
                _append_jsonl(handle, payload, fsync_every_event=fsync_every_event)

            elif message_type == "flush":
                flush_handles()
                put_status(
                    {
                        "type": "flushed",
                        "side_name": side_name,
                        "run_id": current_run_id,
                        "pid": os.getpid(),
                        "wall_time": message.get("wall_time"),
                    }
                )

            elif message_type == "finish_run":
                flush_handles()
                close_handles()
                put_status(
                    {
                        "type": "finished",
                        "side_name": side_name,
                        "run_id": current_run_id,
                        "pid": os.getpid(),
                        "wall_time": message.get("wall_time"),
                    }
                )
                current_run_id = None

            elif message_type == "shutdown":
                if handles:
                    flush_handles()
                    close_handles()
                put_status(
                    {
                        "type": "shutdown_ack",
                        "side_name": side_name,
                        "run_id": current_run_id,
                        "pid": os.getpid(),
                    }
                )
                break

            else:
                raise ValueError(f"Unknown writer message type: {message_type!r}")

        except Exception as exc:
            put_status(
                {
                    "type": "error",
                    "side_name": side_name,
                    "run_id": current_run_id,
                    "pid": os.getpid(),
                    "command_type": message_type,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )


def structured_side_writer_main(
    side_name: str,
    command_queue: Any,
    status_queue: Any,
    fsync_every_event: bool,
) -> None:
    """Run the structured-side writer worker loop.

    The structured-side worker appends per-stream structured events, optionally
    mirrors those events into ``merged.jsonl``, and writes numbered snapshot
    files for playback reconstruction.

    Args:
        side_name: Logical writer side name reported in status messages.
        command_queue: Queue that supplies lifecycle, event, and snapshot
            commands.
        status_queue: Queue used to publish worker status and error payloads.
        fsync_every_event: Whether to fsync each file after individual writes
            and flush operations.

    Returns:
        None.
    """
    stream_handles: dict[str, Any] = {}
    merged_handle: Any | None = None
    snapshots_dir: Path | None = None
    current_run_id: str | None = None

    def put_status(payload: Mapping[str, Any]) -> None:
        """Publish a status payload to the parent process.

        Args:
            payload: Status mapping to copy onto the status queue.

        Returns:
            None.
        """
        status_queue.put(dict(payload))

    def flush_handles() -> None:
        """Flush all open structured stream and merged handles.

        Returns:
            None.
        """
        nonlocal merged_handle
        for handle in stream_handles.values():
            handle.flush()
            if fsync_every_event:
                os.fsync(handle.fileno())
        if merged_handle is not None:
            merged_handle.flush()
            if fsync_every_event:
                os.fsync(merged_handle.fileno())

    def close_handles() -> None:
        """Flush and close all open structured stream and merged handles.

        Returns:
            None.
        """
        nonlocal stream_handles, merged_handle
        for handle in stream_handles.values():
            try:
                handle.flush()
                if fsync_every_event:
                    os.fsync(handle.fileno())
            finally:
                handle.close()
        stream_handles = {}

        if merged_handle is not None:
            try:
                merged_handle.flush()
                if fsync_every_event:
                    os.fsync(merged_handle.fileno())
            finally:
                merged_handle.close()
            merged_handle = None

    while True:
        message = command_queue.get()
        message_type = message["type"]

        try:
            if message_type == "start_run":
                current_run_id = message["run_id"]
                stream_paths = message["stream_paths"]
                merged_path = message["merged_path"]
                snapshots_dir = Path(message["snapshots_dir"])
                snapshots_dir.mkdir(parents=True, exist_ok=True)

                stream_handles = {
                    stream_name: Path(path_str).open("a", encoding="utf-8")
                    for stream_name, path_str in stream_paths.items()
                }
                merged_handle = Path(merged_path).open("a", encoding="utf-8")

                put_status(
                    {
                        "type": "started",
                        "side_name": side_name,
                        "run_id": current_run_id,
                        "pid": os.getpid(),
                    }
                )

            elif message_type == "event":
                if not stream_handles or merged_handle is None:
                    raise RuntimeError(
                        f"{side_name} writer received event before start_run"
                    )

                stream_name = message["stream_name"]
                payload = message["event"]
                write_merged = bool(message.get("write_merged", True))

                stream_handle = stream_handles[stream_name]
                _append_jsonl(
                    stream_handle, payload, fsync_every_event=fsync_every_event
                )

                if write_merged:
                    _append_jsonl(
                        merged_handle, payload, fsync_every_event=fsync_every_event
                    )

            elif message_type == "snapshot":
                if snapshots_dir is None:
                    raise RuntimeError(
                        f"{side_name} writer received snapshot before start_run"
                    )

                snapshot_index = int(message["snapshot_index"])
                snapshot_payload = message["snapshot"]
                snapshot_path = snapshots_dir / f"{snapshot_index:06d}.json"
                temp_path = snapshot_path.with_name(f".{snapshot_path.name}.tmp")

                with temp_path.open("w", encoding="utf-8") as handle:
                    json.dump(
                        snapshot_payload,
                        handle,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, snapshot_path)

                put_status(
                    {
                        "type": "snapshot_written",
                        "side_name": side_name,
                        "run_id": current_run_id,
                        "pid": os.getpid(),
                        "wall_time": snapshot_payload.get("recorded_at"),
                        "snapshot_index": snapshot_index,
                    }
                )

            elif message_type == "flush":
                flush_handles()
                put_status(
                    {
                        "type": "flushed",
                        "side_name": side_name,
                        "run_id": current_run_id,
                        "pid": os.getpid(),
                        "wall_time": message.get("wall_time"),
                    }
                )

            elif message_type == "finish_run":
                flush_handles()
                close_handles()
                put_status(
                    {
                        "type": "finished",
                        "side_name": side_name,
                        "run_id": current_run_id,
                        "pid": os.getpid(),
                        "wall_time": message.get("wall_time"),
                    }
                )
                current_run_id = None
                snapshots_dir = None

            elif message_type == "shutdown":
                if stream_handles or merged_handle is not None:
                    flush_handles()
                    close_handles()
                put_status(
                    {
                        "type": "shutdown_ack",
                        "side_name": side_name,
                        "run_id": current_run_id,
                        "pid": os.getpid(),
                    }
                )
                break

            else:
                raise ValueError(f"Unknown writer message type: {message_type!r}")

        except Exception as exc:
            put_status(
                {
                    "type": "error",
                    "side_name": side_name,
                    "run_id": current_run_id,
                    "pid": os.getpid(),
                    "command_type": message_type,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
