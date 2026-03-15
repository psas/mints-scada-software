from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAW_STREAM_FILES: dict[str, str] = {
    "telemetry_in": "telemetry_in.raw.jsonl",
    "command_out": "command_out.raw.jsonl",
    "operator_action": "operator_action.jsonl",
    "system_event": "system_event.jsonl",
}

STRUCTURED_STREAM_FILES: dict[str, str] = {
    "telemetry_in": "telemetry_in.jsonl",
    "command_out": "command_out.jsonl",
    "operator_action": "operator_action.jsonl",
    "system_event": "system_event.jsonl",
}

INTEGRITY_REPORT_FILENAME = "integrity_report.json"
_SAMPLE_LIMIT = 25


@dataclass(frozen=True)
class ResolvedRunPaths:
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


def scan_run_integrity(
    run_ref: str | Path,
    *,
    project_root: str | Path = ".",
) -> dict[str, Any]:
    paths = _resolve_run_paths(run_ref, project_root=project_root)

    source_roots = {
        "raw": paths.raw_dir,
        "rawbak": paths.rawbak_dir,
        "history": paths.history_dir,
    }

    stream_reports: dict[str, dict[str, Any]] = {}
    for stream_name in RAW_STREAM_FILES:
        source_scans = {
            "raw": _scan_stream_file(
                source_name="raw",
                stream_name=stream_name,
                path=paths.raw_dir / RAW_STREAM_FILES[stream_name],
            ),
            "rawbak": _scan_stream_file(
                source_name="rawbak",
                stream_name=stream_name,
                path=paths.rawbak_dir / RAW_STREAM_FILES[stream_name],
            ),
            "history": _scan_stream_file(
                source_name="history",
                stream_name=stream_name,
                path=paths.history_dir / STRUCTURED_STREAM_FILES[stream_name],
            ),
        }
        stream_reports[stream_name] = _build_stream_report(
            stream_name=stream_name,
            source_scans=source_scans,
        )

    source_presence = {
        source_name: root.is_dir()
        for source_name, root in source_roots.items()
    }

    overall = _build_overall_report(
        run_id=paths.run_id,
        source_presence=source_presence,
        stream_reports=stream_reports,
    )

    return {
        "schema_version": 1,
        "generated_at": utc_now_iso(),
        "run_id": paths.run_id,
        "project_root": str(paths.project_root),
        "source_roots": {
            "raw": str(paths.raw_dir),
            "rawbak": str(paths.rawbak_dir),
            "history": str(paths.history_dir),
        },
        "source_presence": source_presence,
        "overall_status": overall["overall_status"],
        "badge": overall["badge"],
        "summary_message": overall["summary_message"],
        "stream_reports": stream_reports,
    }


def write_run_integrity_report(
    run_ref: str | Path,
    *,
    project_root: str | Path = ".",
    report: dict[str, Any] | None = None,
) -> Path:
    paths = _resolve_run_paths(run_ref, project_root=project_root)
    payload = report if report is not None else scan_run_integrity(run_ref, project_root=project_root)

    if not paths.history_dir.is_dir():
        raise FileNotFoundError(
            f"Cannot write integrity report because history directory does not exist: {paths.history_dir}"
        )

    report_path = paths.history_dir / INTEGRITY_REPORT_FILENAME
    _atomic_write_json(report_path, payload)
    return report_path


def scan_and_write_run_integrity(
    run_ref: str | Path,
    *,
    project_root: str | Path = ".",
) -> tuple[dict[str, Any], Path]:
    report = scan_run_integrity(run_ref, project_root=project_root)
    report_path = write_run_integrity_report(
        run_ref,
        project_root=project_root,
        report=report,
    )
    return report, report_path


def _resolve_run_paths(run_ref: str | Path, *, project_root: str | Path) -> ResolvedRunPaths:
    project_root_path = Path(project_root).expanduser().resolve()
    raw_root = project_root_path / ".ignitionraw"
    rawbak_root = project_root_path / ".ignitionrawbak"
    history_root = project_root_path / "ignitionhistory"

    ref_path = Path(run_ref).expanduser()
    if ref_path.exists():
        ref_path = ref_path.resolve()
        if ref_path.is_file():
            ref_path = ref_path.parent
        run_id = ref_path.name
    else:
        run_id = str(run_ref)

    return ResolvedRunPaths(
        project_root=project_root_path,
        run_id=run_id,
        raw_dir=raw_root / run_id,
        rawbak_dir=rawbak_root / run_id,
        history_dir=history_root / run_id,
    )


def _scan_stream_file(*, source_name: str, stream_name: str, path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source_name": source_name,
        "stream_name": stream_name,
        "path": str(path),
        "present": path.is_file(),
        "count": 0,
        "identity_count": 0,
        "missing_identity_count": 0,
        "parse_error_count": 0,
        "parse_errors_sample": [],
        "duplicate_event_uid_count": 0,
        "duplicate_event_uid_sample": [],
        "sequence_issue_count": 0,
        "sequence_issue_sample": [],
        "first_recorded_at": None,
        "last_recorded_at": None,
        "events_by_uid": {},
    }

    if not path.is_file():
        return result

    seen_uids: set[str] = set()
    stream_seqs: list[int] = []

    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                result["parse_error_count"] += 1
                if len(result["parse_errors_sample"]) < _SAMPLE_LIMIT:
                    result["parse_errors_sample"].append(
                        {
                            "line": line_number,
                            "error": str(exc),
                        }
                    )
                continue

            result["count"] += 1

            recorded_at = payload.get("recorded_at")
            if isinstance(recorded_at, str) and recorded_at.strip():
                if result["first_recorded_at"] is None:
                    result["first_recorded_at"] = recorded_at.strip()
                result["last_recorded_at"] = recorded_at.strip()

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
                result["missing_identity_count"] += 1
                continue

            event_uid = event_uid.strip()
            canonical_hash = canonical_hash.strip()
            result["identity_count"] += 1
            stream_seqs.append(int(stream_seq))

            if event_uid in seen_uids:
                result["duplicate_event_uid_count"] += 1
                if len(result["duplicate_event_uid_sample"]) < _SAMPLE_LIMIT:
                    result["duplicate_event_uid_sample"].append(event_uid)
            seen_uids.add(event_uid)

            existing = result["events_by_uid"].get(event_uid)
            if existing is None:
                result["events_by_uid"][event_uid] = {
                    "event_uid": event_uid,
                    "canonical_hash": canonical_hash,
                    "stream_seq": int(stream_seq),
                    "recorded_at": payload.get("recorded_at"),
                }

    result["sequence_issue_count"], result["sequence_issue_sample"] = _scan_sequence_issues(stream_seqs)
    return result


def _scan_sequence_issues(stream_seqs: list[int]) -> tuple[int, list[dict[str, Any]]]:
    if not stream_seqs:
        return 0, []

    issues: list[dict[str, Any]] = []
    unique_sorted = sorted(set(stream_seqs))

    if unique_sorted[0] != 1:
        issues.append(
            {
                "type": "sequence_does_not_start_at_one",
                "first_seq": unique_sorted[0],
            }
        )

    previous = unique_sorted[0]
    for current in unique_sorted[1:]:
        if current != previous + 1:
            issues.append(
                {
                    "type": "sequence_gap",
                    "after": previous,
                    "before": current,
                }
            )
            if len(issues) >= _SAMPLE_LIMIT:
                break
        previous = current

    return len(issues), issues[:_SAMPLE_LIMIT]


def _build_stream_report(
    *,
    stream_name: str,
    source_scans: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    present_sources = [name for name, scan in source_scans.items() if scan["present"]]
    uid_union: set[str] = set()
    for scan in source_scans.values():
        uid_union.update(scan["events_by_uid"].keys())

    missing_by_source: dict[str, list[str]] = {}
    hash_mismatches: list[dict[str, Any]] = []
    sequence_mismatches: list[dict[str, Any]] = []

    for source_name, scan in source_scans.items():
        missing = sorted(uid for uid in uid_union if uid not in scan["events_by_uid"])
        missing_by_source[source_name] = missing[:_SAMPLE_LIMIT]

    for event_uid in sorted(uid_union):
        present_event_records = {
            source_name: scan["events_by_uid"].get(event_uid)
            for source_name, scan in source_scans.items()
            if event_uid in scan["events_by_uid"]
        }
        hashes = {
            source_name: record["canonical_hash"]
            for source_name, record in present_event_records.items()
        }
        seqs = {
            source_name: record["stream_seq"]
            for source_name, record in present_event_records.items()
        }

        if len(set(hashes.values())) > 1 and len(hash_mismatches) < _SAMPLE_LIMIT:
            hash_mismatches.append(
                {
                    "event_uid": event_uid,
                    "hashes": hashes,
                }
            )

        if len(set(seqs.values())) > 1 and len(sequence_mismatches) < _SAMPLE_LIMIT:
            sequence_mismatches.append(
                {
                    "event_uid": event_uid,
                    "stream_seqs": seqs,
                }
            )

    present_source_count = len(present_sources)
    has_parse_errors = any(scan["parse_error_count"] > 0 for scan in source_scans.values())
    has_missing_identity = any(scan["missing_identity_count"] > 0 for scan in source_scans.values())
    has_duplicates = any(scan["duplicate_event_uid_count"] > 0 for scan in source_scans.values())
    has_sequence_issues = any(scan["sequence_issue_count"] > 0 for scan in source_scans.values())
    has_hash_mismatch = bool(hash_mismatches)
    has_seq_mismatch = bool(sequence_mismatches)
    has_missing_events = any(bool(values) for values in missing_by_source.values())

    if present_source_count == 0:
        status = "missing"
        badge = "red"
        message = f"No archive sources found for stream {stream_name}"
    elif has_parse_errors or has_missing_identity or has_duplicates or has_hash_mismatch or has_seq_mismatch:
        status = "mismatch"
        badge = "red"
        message = f"Data does not match for stream {stream_name}"
    elif has_sequence_issues:
        status = "mismatch"
        badge = "red"
        message = f"Sequence issues detected for stream {stream_name}"
    elif present_source_count < 3 or has_missing_events:
        status = "partial"
        badge = "yellow"
        missing_sources = [name for name, scan in source_scans.items() if not scan["present"]]
        if missing_sources:
            joined = ", ".join(missing_sources)
            message = f"Missing from {joined}, but rest data matches for stream {stream_name}"
        else:
            message = f"Missing event coverage detected for stream {stream_name}"
    else:
        status = "ok"
        badge = "green"
        message = f"All data matches natively for stream {stream_name}"

    return {
        "stream_name": stream_name,
        "status": status,
        "badge": badge,
        "message": message,
        "present_sources": present_sources,
        "source_summaries": {
            source_name: _summarize_source_scan(scan)
            for source_name, scan in source_scans.items()
        },
        "missing_event_uid_sample_by_source": {
            source_name: values
            for source_name, values in missing_by_source.items()
            if values
        },
        "hash_mismatch_count": len(hash_mismatches),
        "hash_mismatch_sample": hash_mismatches,
        "stream_seq_mismatch_count": len(sequence_mismatches),
        "stream_seq_mismatch_sample": sequence_mismatches,
    }


def _summarize_source_scan(scan: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": scan["path"],
        "present": scan["present"],
        "count": scan["count"],
        "identity_count": scan["identity_count"],
        "missing_identity_count": scan["missing_identity_count"],
        "parse_error_count": scan["parse_error_count"],
        "parse_errors_sample": scan["parse_errors_sample"],
        "duplicate_event_uid_count": scan["duplicate_event_uid_count"],
        "duplicate_event_uid_sample": scan["duplicate_event_uid_sample"],
        "sequence_issue_count": scan["sequence_issue_count"],
        "sequence_issue_sample": scan["sequence_issue_sample"],
        "first_recorded_at": scan["first_recorded_at"],
        "last_recorded_at": scan["last_recorded_at"],
    }


def _build_overall_report(
    *,
    run_id: str,
    source_presence: dict[str, bool],
    stream_reports: dict[str, dict[str, Any]],
) -> dict[str, str]:
    if any(report["status"] == "mismatch" for report in stream_reports.values()):
        return {
            "overall_status": "mismatch",
            "badge": "red",
            "summary_message": "Data does not match",
        }

    missing_sources = [name for name, present in source_presence.items() if not present]
    if missing_sources:
        joined = ", ".join(missing_sources)
        return {
            "overall_status": "partial",
            "badge": "yellow",
            "summary_message": f"Missing from {joined}",
        }

    if any(report["status"] == "partial" for report in stream_reports.values()):
        return {
            "overall_status": "partial",
            "badge": "yellow",
            "summary_message": "Missing from one or more sources, but remaining data matches",
        }

    if all(report["status"] == "ok" for report in stream_reports.values()):
        return {
            "overall_status": "ok",
            "badge": "green",
            "summary_message": "All data matches natively",
        }

    return {
        "overall_status": "unknown",
        "badge": "red",
        "summary_message": f"Unable to determine archive integrity for run {run_id}",
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    temp_path.replace(path)
