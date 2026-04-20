"""gui/playback_export.py

Playback export helpers for run directories and seek-ordered event lists.

This module loads merged playback artifacts from a recorded run directory and
exports playback events as JSONL or flattened CSV. It supports both
directory-based exports from ``merged.jsonl`` on disk and in-memory exports from
the seek-ordered event list used by playback.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_playback_artifacts(
    run_dir: str | Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load playback metadata and merged events from a recorded run directory.

    Args:
        run_dir: Path to the recorded run directory that contains
            ``metadata.json`` and optionally ``merged.jsonl``.

    Returns:
        A tuple of ``(metadata, merged_events)`` where ``metadata`` is the
        decoded run metadata and ``merged_events`` is the list of decoded events
        from ``merged.jsonl`` in file order. When ``merged.jsonl`` is missing,
        the event list is empty.

    Raises:
        FileNotFoundError: If ``metadata.json`` does not exist.
        json.JSONDecodeError: If ``metadata.json`` or any non-empty line in
            ``merged.jsonl`` is not valid JSON.
        OSError: If the run directory contents cannot be read.
    """
    resolved = Path(run_dir).expanduser().resolve()
    metadata = json.loads((resolved / "metadata.json").read_text(encoding="utf-8"))
    merged_events: list[dict[str, Any]] = []
    merged_path = resolved / "merged.jsonl"
    if merged_path.is_file():
        with merged_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                merged_events.append(json.loads(line))
    return metadata, merged_events


def flatten_event_for_csv(event: dict[str, Any]) -> dict[str, Any]:
    """Flatten a merged playback event into a CSV-friendly row.

    The flattened row preserves a stable set of top-level event columns and
    expands supported nested mappings under ``semantic_`` and
    ``device_state_`` prefixes.

    Args:
        event: Playback event dictionary to flatten.

    Returns:
        A flat dictionary suitable for CSV export.
    """
    flattened: dict[str, Any] = {
        "recorded_at": event.get("recorded_at"),
        "stream": event.get("stream"),
        "event_uid": event.get("event_uid"),
        "global_seq": event.get("global_seq"),
        "stream_seq": event.get("stream_seq"),
        "event_kind": event.get("event_kind"),
        "event_type": event.get("event_type"),
        "device_id": event.get("device_id"),
        "command_name": event.get("command_name"),
        "status": event.get("status"),
        "message": event.get("message"),
    }

    semantic_fields = event.get("semantic_fields")
    if isinstance(semantic_fields, dict):
        for key, value in semantic_fields.items():
            flattened[f"semantic_{key}"] = value

    device_state = event.get("device_state")
    if isinstance(device_state, dict):
        for key, value in device_state.items():
            flattened[f"device_state_{key}"] = value

    return flattened


def export_run_jsonl(
    run_dir: str | Path,
    output_path: str | Path,
    *,
    stream_filter: set[str] | None = None,
) -> str:
    """Export merged run events from disk to a JSONL file.

    Args:
        run_dir: Path to the recorded run directory.
        output_path: Destination JSONL path.
        stream_filter: Optional set of stream names to include. When omitted,
            all merged events are exported.

    Returns:
        The resolved destination path as a string.

    Raises:
        FileNotFoundError: If required run artifacts are missing.
        json.JSONDecodeError: If an input artifact contains invalid JSON.
        OSError: If input artifacts cannot be read or the output file cannot be
            written.
    """
    _, merged_events = load_playback_artifacts(run_dir)
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for event in merged_events:
            stream_name = event.get("stream")
            if stream_filter and stream_name not in stream_filter:
                continue
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=False))
            handle.write("\n")
    return str(destination)


def export_run_csv(
    run_dir: str | Path,
    output_path: str | Path,
    *,
    stream_filter: set[str] | None = None,
) -> str:
    """Export merged run events from disk to flattened CSV.

    Column order is derived from the first appearance of keys across the
    flattened rows that pass the stream filter.

    Args:
        run_dir: Path to the recorded run directory.
        output_path: Destination CSV path.
        stream_filter: Optional set of stream names to include. When omitted,
            all merged events are exported.

    Returns:
        The resolved destination path as a string.

    Raises:
        FileNotFoundError: If required run artifacts are missing.
        json.JSONDecodeError: If an input artifact contains invalid JSON.
        OSError: If input artifacts cannot be read or the output file cannot be
            written.
    """
    _, merged_events = load_playback_artifacts(run_dir)
    rows = []
    all_columns: list[str] = []
    seen: set[str] = set()
    for event in merged_events:
        stream_name = event.get("stream")
        if stream_filter and stream_name not in stream_filter:
            continue
        row = flatten_event_for_csv(event)
        rows.append(row)
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                all_columns.append(key)

    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=all_columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return str(destination)


def export_events_jsonl(
    events: list[dict[str, Any]],
    output_path: str | Path,
    *,
    stream_filter: set[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Export seek-ordered playback events to JSONL.

    Events are exported directly from the manager's seek_events list, which is
    sorted by ``(timestamp_key, original_index)`` — the same order that playback
    seek and advance use. This guarantees export ordering matches what the user
    sees during playback.

    When ``metadata`` is provided, the file begins with a header record marked
    by ``_export_metadata``.

    Args:
        events: Pre-sorted playback events, typically from
            ``PlaybackStateManager.seek_events``.
        output_path: Destination JSONL path.
        stream_filter: Optional set of stream names to include. When omitted,
            all events are exported.
        metadata: Optional export metadata to merge into the leading header
            record.

    Returns:
        The number of event records written, excluding the optional metadata
        header.

    Raises:
        OSError: If the output file cannot be written.
        TypeError: If an event or metadata value cannot be serialized as JSON.
    """
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with destination.open("w", encoding="utf-8") as handle:
        if metadata:
            header = {
                "_export_metadata": True,
                "exported_at": datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
            }
            header.update(metadata)
            handle.write(json.dumps(header, ensure_ascii=False, sort_keys=False))
            handle.write("\n")
        for event in events:
            if stream_filter and event.get("stream") not in stream_filter:
                continue
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=False))
            handle.write("\n")
            count += 1
    return count


def export_events_csv(
    events: list[dict[str, Any]],
    output_path: str | Path,
    *,
    stream_filter: set[str] | None = None,
) -> int:
    """Export seek-ordered playback events to flattened CSV.

    Column order is derived from the first appearance of keys across the
    flattened rows that pass the stream filter.

    Args:
        events: Pre-sorted playback events, typically from
            ``PlaybackStateManager.seek_events``.
        output_path: Destination CSV path.
        stream_filter: Optional set of stream names to include. When omitted,
            all events are exported.

    Returns:
        The number of CSV rows written.

    Raises:
        OSError: If the output file cannot be written.
    """
    rows: list[dict[str, Any]] = []
    all_columns: list[str] = []
    seen: set[str] = set()
    for event in events:
        if stream_filter and event.get("stream") not in stream_filter:
            continue
        row = flatten_event_for_csv(event)
        rows.append(row)
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                all_columns.append(key)

    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=all_columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)
