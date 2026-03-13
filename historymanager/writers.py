from __future__ import annotations

import json
import os
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass
class WriterRuntime:
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


def raw_side_writer_main(
    side_name: str,
    command_queue: Any,
    status_queue: Any,
    fsync_every_event: bool,
) -> None:
    handles: dict[str, Any] = {}
    current_run_id: str | None = None

    def put_status(payload: Mapping[str, Any]) -> None:
        status_queue.put(dict(payload))

    def flush_handles() -> None:
        for handle in handles.values():
            handle.flush()
            if fsync_every_event:
                os.fsync(handle.fileno())

    def close_handles() -> None:
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
                    raise RuntimeError(f"{side_name} writer received event before start_run")

                stream_name = message["stream_name"]
                payload = message["event"]
                handle = handles[stream_name]

                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=False))
                handle.write("\n")
                handle.flush()

                if fsync_every_event:
                    os.fsync(handle.fileno())

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