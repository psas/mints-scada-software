# gui/playback_catalog.py

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from historymanager.integrity import INTEGRITY_REPORT_FILENAME, scan_run_integrity
from historymanager.paths import HISTORY_ROOT_DIRNAME


@dataclass(frozen=True)
class PlaybackRunSummary:
    run_id: str
    run_dir: Path
    metadata_path: Path
    complete_path: Path
    snapshots_dir: Path
    start_wall_time: str | None
    end_wall_time: str | None
    status: str
    mode: str | None
    test_name: str | None
    operator: str | None
    profile_name: str | None
    notes: str | None
    snapshot_count: int
    has_merged: bool
    integrity_status: str
    integrity_badge: str
    integrity_summary_message: str
    integrity_report_path: Path | None
    integrity_report: dict[str, Any] | None

    @property
    def sort_key(self) -> tuple[int, str]:
        parsed = _parse_iso_wall_time(self.start_wall_time)
        if parsed is None:
            return (0, self.run_id)
        return (int(parsed.timestamp()), self.run_id)

    @property
    def display_title(self) -> str:
        test_name = (self.test_name or "").strip()
        if test_name and test_name != self.run_id:
            return f"{self.run_id}  -  {test_name}"
        return self.run_id

    @property
    def integrity_compact_label(self) -> str:
        if self.integrity_badge == "green":
            return "archive=ok"
        if self.integrity_badge == "yellow":
            return "archive=check"
        if self.integrity_badge == "red":
            return "archive=mismatch"
        return f"archive={self.integrity_status or 'unknown'}"

    @property
    def display_subtitle(self) -> str:
        parts: list[str] = []

        if self.mode:
            parts.append(self.mode)
        if self.status:
            parts.append(self.status)
        if self.operator:
            parts.append(f"operator={self.operator}")
        if self.profile_name:
            parts.append(f"profile={self.profile_name}")
        if self.start_wall_time:
            parts.append(f"start={self.start_wall_time}")
        if self.end_wall_time:
            parts.append(f"end={self.end_wall_time}")

        parts.append(f"snapshots={self.snapshot_count}")
        parts.append("merged=yes" if self.has_merged else "merged=no")
        parts.append(self.integrity_compact_label)

        summary = (self.integrity_summary_message or "").strip()
        if summary:
            parts.append(f"integrity={summary}")

        return " | ".join(parts)

    @property
    def tooltip_text(self) -> str:
        lines = [
            f"Run ID: {self.run_id}",
            f"Path: {self.run_dir}",
            f"Status: {self.status}",
        ]

        if self.test_name:
            lines.append(f"Test name: {self.test_name}")
        if self.mode:
            lines.append(f"Mode: {self.mode}")
        if self.operator:
            lines.append(f"Operator: {self.operator}")
        if self.profile_name:
            lines.append(f"Profile: {self.profile_name}")
        if self.start_wall_time:
            lines.append(f"Start: {self.start_wall_time}")
        if self.end_wall_time:
            lines.append(f"End: {self.end_wall_time}")
        lines.append(f"Snapshots: {self.snapshot_count}")
        lines.append(f"Merged timeline: {'yes' if self.has_merged else 'no'}")
        lines.append(f"Integrity status: {self.integrity_status}")
        lines.append(f"Integrity badge: {self.integrity_badge}")
        if self.integrity_summary_message:
            lines.append(f"Integrity summary: {self.integrity_summary_message}")
        if self.integrity_report_path is not None:
            lines.append(f"Integrity report: {self.integrity_report_path}")

        if self.notes:
            lines.append("")
            lines.append(self.notes)

        return "\n".join(lines)


def discover_playback_runs(
    project_root: str | Path,
    *,
    include_integrity: bool = True,
) -> list[PlaybackRunSummary]:
    project_root_path = Path(project_root).expanduser().resolve()
    history_root = project_root_path / HISTORY_ROOT_DIRNAME
    if not history_root.is_dir():
        return []

    summaries: list[PlaybackRunSummary] = []
    for child in history_root.iterdir():
        if not child.is_dir():
            continue

        metadata_path = child / "metadata.json"
        if not metadata_path.is_file():
            continue

        try:
            metadata = _load_metadata(metadata_path)
        except Exception:
            continue

        snapshots_dir = child / "snapshots"
        snapshot_count = len(list(snapshots_dir.glob("*.json"))) if snapshots_dir.is_dir() else 0
        integrity_report: dict[str, Any] | None = None
        integrity_report_path: Path | None = None
        integrity_status = "unknown"
        integrity_badge = "red"
        integrity_summary_message = "Integrity details unavailable."

        if include_integrity:
            integrity_report_path = child / INTEGRITY_REPORT_FILENAME
            integrity_report = _load_integrity_report_if_present(integrity_report_path)
            if integrity_report is None:
                integrity_report = _scan_integrity_report(child, project_root=project_root_path)
            if isinstance(integrity_report, dict):
                integrity_status = _coerce_optional_str(integrity_report.get("overall_status")) or "unknown"
                integrity_badge = _coerce_optional_str(integrity_report.get("badge")) or "red"
                integrity_summary_message = (
                    _coerce_optional_str(integrity_report.get("summary_message"))
                    or "Integrity details unavailable."
                )
                if integrity_report_path is not None and not integrity_report_path.is_file():
                    integrity_report_path = None

        summaries.append(
            PlaybackRunSummary(
                run_id=str(metadata.get("run_id") or child.name),
                run_dir=child,
                metadata_path=metadata_path,
                complete_path=child / "complete.json",
                snapshots_dir=snapshots_dir,
                start_wall_time=_coerce_optional_str(metadata.get("start_wall_time")),
                end_wall_time=_coerce_optional_str(metadata.get("end_wall_time")),
                status=_coerce_optional_str(metadata.get("status")) or "unknown",
                mode=_coerce_optional_str(metadata.get("mode")),
                test_name=_coerce_optional_str(metadata.get("test_name")),
                operator=_coerce_optional_str(metadata.get("operator")),
                profile_name=_coerce_optional_str(metadata.get("profile_name")),
                notes=_coerce_optional_str(metadata.get("notes")),
                snapshot_count=snapshot_count,
                has_merged=(child / "merged.jsonl").is_file(),
                integrity_status=integrity_status,
                integrity_badge=integrity_badge,
                integrity_summary_message=integrity_summary_message,
                integrity_report_path=integrity_report_path,
                integrity_report=integrity_report,
            )
        )

    summaries.sort(key=lambda summary: summary.sort_key, reverse=True)
    return summaries


def _load_metadata(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _load_integrity_report_if_present(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _scan_integrity_report(run_dir: Path, *, project_root: Path) -> dict[str, Any] | None:
    try:
        report = scan_run_integrity(run_dir, project_root=project_root)
    except Exception:
        return None
    return report if isinstance(report, dict) else None


def _coerce_optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _parse_iso_wall_time(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
