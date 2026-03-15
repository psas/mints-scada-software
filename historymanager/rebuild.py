from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .integrity import RAW_STREAM_FILES, STRUCTURED_STREAM_FILES

REBUILD_WORKSPACE_DIRNAME = ".rebuild_workspace"
REBUILD_PREVIEW_FILENAME = "rebuild_preview.json"

_PASS_THROUGH_STREAMS = {"command_out", "operator_action", "system_event"}


@dataclass(frozen=True)
class RebuildRunPaths:
    project_root: Path
    run_id: str
    raw_dir: Path
    rawbak_dir: Path
    history_dir: Path


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def rebuild_run_archive(
    run_ref: str | Path,
    *,
    project_root: str | Path = ".",
    keep_workspace: bool = True,
) -> dict[str, Any]:
    paths = _resolve_run_paths(run_ref, project_root=project_root)

    source_presence = {
        "raw": paths.raw_dir.is_dir(),
        "rawbak": paths.rawbak_dir.is_dir(),
        "history": paths.history_dir.is_dir(),
    }

    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": utc_now_iso(),
        "run_id": paths.run_id,
        "project_root": str(paths.project_root),
        "source_paths": {
            "raw": str(paths.raw_dir),
            "rawbak": str(paths.rawbak_dir),
            "history": str(paths.history_dir),
        },
        "source_presence": source_presence,
        "status": "failed",
        "summary_message": "",
        "failure_reasons": [],
        "stream_reports": {},
        "temp_workspace": None,
    }

    canonical_raw_by_stream: dict[str, list[dict[str, Any]]] = {}
    history_rebuild_by_stream: dict[str, list[dict[str, Any]]] = {}
    existing_history_by_stream: dict[str, list[dict[str, Any]]] = {}

    fatal_reasons: list[str] = []

    for stream_name in RAW_STREAM_FILES:
        raw_scan = _load_event_file(paths.raw_dir / RAW_STREAM_FILES[stream_name])
        rawbak_scan = _load_event_file(paths.rawbak_dir / RAW_STREAM_FILES[stream_name])
        history_scan = _load_event_file(paths.history_dir / STRUCTURED_STREAM_FILES[stream_name])

        stream_report = _build_stream_rebuild_plan(
            stream_name=stream_name,
            raw_scan=raw_scan,
            rawbak_scan=rawbak_scan,
            history_scan=history_scan,
        )
        report["stream_reports"][stream_name] = stream_report

        if stream_report["status"] == "failed":
            fatal_reasons.extend(stream_report["issues"])
            continue

        canonical_raw_by_stream[stream_name] = stream_report["canonical_raw_events"]
        history_rebuild_by_stream[stream_name] = stream_report["rebuilt_history_events"]
        existing_history_by_stream[stream_name] = stream_report["existing_history_events"]

    if fatal_reasons:
        report["status"] = "failed"
        report["failure_reasons"] = fatal_reasons
        report["summary_message"] = "Rebuild failed, please check data manually"
        return report

    temp_workspace = _create_rebuild_workspace(
        paths=paths,
        canonical_raw_by_stream=canonical_raw_by_stream,
        history_rebuild_by_stream=history_rebuild_by_stream,
        existing_history_by_stream=existing_history_by_stream,
    )
    report["temp_workspace"] = str(temp_workspace)
    report["status"] = "ready"
    report["summary_message"] = "Safe rebuild workspace created"

    preview_path = temp_workspace / REBUILD_PREVIEW_FILENAME
    _atomic_write_json(preview_path, report)

    if not keep_workspace:
        shutil.rmtree(temp_workspace, ignore_errors=True)
        report["temp_workspace"] = None

    return report


def discard_rebuild_workspace(workspace_path: str | Path) -> None:
    path = Path(workspace_path).expanduser().resolve()
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _resolve_run_paths(run_ref: str | Path, *, project_root: str | Path) -> RebuildRunPaths:
    project_root_path = Path(project_root).expanduser().resolve()
    raw_root = project_root_path / ".ignitionraw"
    rawbak_root = project_root_path / ".ignitionrawbak"
    history_root = project_root_path / "ignitionhistory"

    ref_path = Path(run_ref).expanduser()
    if ref_path.exists():
        resolved = ref_path.resolve()
        if resolved.is_file():
            resolved = resolved.parent
        run_id = resolved.name
    else:
        run_id = str(run_ref)

    return RebuildRunPaths(
        project_root=project_root_path,
        run_id=run_id,
        raw_dir=raw_root / run_id,
        rawbak_dir=rawbak_root / run_id,
        history_dir=history_root / run_id,
    )


def _load_event_file(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "present": path.is_file(),
        "events": [],
        "events_by_uid": {},
        "parse_errors": [],
        "duplicate_uids": [],
        "missing_identity": [],
    }

    if not path.is_file():
        return result

    seen_uids: set[str] = set()

    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                result["parse_errors"].append(
                    {
                        "line": line_number,
                        "error": str(exc),
                    }
                )
                continue

            event_uid = payload.get("event_uid")
            canonical_hash = payload.get("canonical_hash")
            stream_seq = payload.get("stream_seq")

            if (
                not isinstance(event_uid, str)
                or not event_uid.strip()
                or not isinstance(canonical_hash, str)
                or not canonical_hash.strip()
                or not isinstance(stream_seq, int)
                or stream_seq < 1
            ):
                result["missing_identity"].append(
                    {
                        "line": line_number,
                        "event_uid": payload.get("event_uid"),
                        "canonical_hash": payload.get("canonical_hash"),
                        "stream_seq": payload.get("stream_seq"),
                    }
                )
                continue

            event_uid = event_uid.strip()
            canonical_hash = canonical_hash.strip()

            if event_uid in seen_uids:
                result["duplicate_uids"].append(event_uid)
                continue

            seen_uids.add(event_uid)
            result["events"].append(payload)
            result["events_by_uid"][event_uid] = payload

    result["events"].sort(key=_event_sort_key)
    return result


def _build_stream_rebuild_plan(
    *,
    stream_name: str,
    raw_scan: dict[str, Any],
    rawbak_scan: dict[str, Any],
    history_scan: dict[str, Any],
) -> dict[str, Any]:
    issues: list[str] = []

    for source_name, scan in (
        ("raw", raw_scan),
        ("rawbak", rawbak_scan),
        ("history", history_scan),
    ):
        if scan["parse_errors"]:
            issues.append(f"{stream_name}: {source_name} has parse errors")
        if scan["duplicate_uids"]:
            issues.append(f"{stream_name}: {source_name} has duplicate event_uid values")
        if scan["missing_identity"]:
            issues.append(f"{stream_name}: {source_name} has events missing shared identity fields")

    raw_present = raw_scan["present"]
    rawbak_present = rawbak_scan["present"]
    history_present = history_scan["present"]

    raw_events = raw_scan["events_by_uid"]
    rawbak_events = rawbak_scan["events_by_uid"]
    history_events = history_scan["events_by_uid"]

    canonical_raw_events: dict[str, dict[str, Any]] = {}
    canonical_strategy = "none"

    if raw_present or rawbak_present:
        canonical_strategy = "union"
        for event_uid, payload in raw_events.items():
            canonical_raw_events[event_uid] = payload
        for event_uid, payload in rawbak_events.items():
            existing = canonical_raw_events.get(event_uid)
            if existing is None:
                canonical_raw_events[event_uid] = payload
                continue

            if existing.get("canonical_hash") != payload.get("canonical_hash"):
                issues.append(
                    f"{stream_name}: raw/rawbak conflict for event_uid {event_uid}"
                )
            if existing.get("stream_seq") != payload.get("stream_seq"):
                issues.append(
                    f"{stream_name}: raw/rawbak stream_seq mismatch for event_uid {event_uid}"
                )
    else:
        if history_present:
            issues.append(
                f"{stream_name}: missing both raw and rawbak first-order sources"
            )

    rebuilt_history_events: list[dict[str, Any]] = []
    history_strategy = "reuse"

    if not issues:
        canonical_sorted = sorted(canonical_raw_events.values(), key=_event_sort_key)

        if stream_name in _PASS_THROUGH_STREAMS:
            if not history_present:
                history_strategy = "rebuild_from_first_order"
                rebuilt_history_events = [dict(event) for event in canonical_sorted]
            else:
                history_matches = _history_matches_canonical(
                    canonical_raw_events=canonical_raw_events,
                    history_events=history_events,
                )
                if history_matches:
                    rebuilt_history_events = sorted(history_scan["events"], key=_event_sort_key)
                    history_strategy = "reuse"
                else:
                    rebuilt_history_events = [dict(event) for event in canonical_sorted]
                    history_strategy = "rebuild_from_first_order"
        else:
            # telemetry_in: safe rebuild requires a reducer/structured builder replay path.
            if history_present and _history_matches_canonical(
                canonical_raw_events=canonical_raw_events,
                history_events=history_events,
            ):
                rebuilt_history_events = sorted(history_scan["events"], key=_event_sort_key)
                history_strategy = "reuse"
            elif canonical_raw_events:
                issues.append(
                    "telemetry_in: structured rebuild requires reducer/structured replay and is not available in safe rebuild mode"
                )

        if not canonical_raw_events and not rebuilt_history_events and not history_present:
            issues.append(f"{stream_name}: no usable archive data found")

    status = "ready" if not issues else "failed"
    message = (
        f"Safe rebuild plan ready for stream {stream_name}"
        if status == "ready"
        else f"Rebuild failed for stream {stream_name}"
    )

    return {
        "stream_name": stream_name,
        "status": status,
        "message": message,
        "canonical_source_strategy": canonical_strategy,
        "history_strategy": history_strategy,
        "raw_present": raw_present,
        "rawbak_present": rawbak_present,
        "history_present": history_present,
        "canonical_event_count": len(canonical_raw_events),
        "rebuilt_history_event_count": len(rebuilt_history_events),
        "issues": issues,
        "canonical_raw_events": sorted(canonical_raw_events.values(), key=_event_sort_key),
        "rebuilt_history_events": rebuilt_history_events,
        "existing_history_events": sorted(history_scan["events"], key=_event_sort_key),
    }


def _history_matches_canonical(
    *,
    canonical_raw_events: dict[str, dict[str, Any]],
    history_events: dict[str, dict[str, Any]],
) -> bool:
    if set(canonical_raw_events.keys()) != set(history_events.keys()):
        return False

    for event_uid, canonical_payload in canonical_raw_events.items():
        history_payload = history_events.get(event_uid)
        if history_payload is None:
            return False
        if canonical_payload.get("canonical_hash") != history_payload.get("canonical_hash"):
            return False
        if canonical_payload.get("stream_seq") != history_payload.get("stream_seq"):
            return False
    return True


def _create_rebuild_workspace(
    *,
    paths: RebuildRunPaths,
    canonical_raw_by_stream: dict[str, list[dict[str, Any]]],
    history_rebuild_by_stream: dict[str, list[dict[str, Any]]],
    existing_history_by_stream: dict[str, list[dict[str, Any]]],
) -> Path:
    workspace_root = paths.history_dir / REBUILD_WORKSPACE_DIRNAME
    workspace_root.mkdir(parents=True, exist_ok=True)

    workspace = workspace_root / f"{utc_now_iso().replace(':', '-')}_{uuid.uuid4().hex[:8]}"
    raw_out = workspace / "raw"
    rawbak_out = workspace / "rawbak"
    history_out = workspace / "history"
    snapshots_out = history_out / "snapshots"

    raw_out.mkdir(parents=True, exist_ok=True)
    rawbak_out.mkdir(parents=True, exist_ok=True)
    history_out.mkdir(parents=True, exist_ok=True)
    snapshots_out.mkdir(parents=True, exist_ok=True)

    for stream_name, filename in RAW_STREAM_FILES.items():
        _write_jsonl(raw_out / filename, canonical_raw_by_stream.get(stream_name, []))
        _write_jsonl(rawbak_out / filename, canonical_raw_by_stream.get(stream_name, []))

    merged_events: list[dict[str, Any]] = []
    for stream_name, filename in STRUCTURED_STREAM_FILES.items():
        events = history_rebuild_by_stream.get(stream_name) or existing_history_by_stream.get(stream_name, [])
        _write_jsonl(history_out / filename, events)
        merged_events.extend(events)

    merged_events.sort(key=_event_sort_key)
    _write_jsonl(history_out / "merged.jsonl", merged_events)

    _copy_if_exists(paths.history_dir / "metadata.json", history_out / "metadata.json")
    _copy_if_exists(paths.history_dir / "writer_stats.json", history_out / "writer_stats.json")
    _copy_if_exists(paths.history_dir / "complete.json", history_out / "complete.json")

    original_snapshots = paths.history_dir / "snapshots"
    if original_snapshots.is_dir():
        for snapshot_file in sorted(original_snapshots.glob("*.json")):
            shutil.copy2(snapshot_file, snapshots_out / snapshot_file.name)

    return workspace


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for payload in events:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=False)
            handle.write("\n")


def _copy_if_exists(source: Path, destination: Path) -> None:
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _event_sort_key(payload: dict[str, Any]) -> tuple[str, int, str]:
    recorded_at = payload.get("recorded_at")
    if not isinstance(recorded_at, str):
        recorded_at = ""
    stream_seq = payload.get("stream_seq")
    if not isinstance(stream_seq, int):
        stream_seq = 0
    event_uid = payload.get("event_uid")
    if not isinstance(event_uid, str):
        event_uid = ""
    return (recorded_at, stream_seq, event_uid)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    temp_path.replace(path)
