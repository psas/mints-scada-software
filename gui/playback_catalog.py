# gui/playback_catalog.py

"""Discover and summarize recorded runs available for playback selection."""

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
    """Summarize one recorded run discovered under ``ignitionhistory``.

    The summary collects metadata, snapshot availability, merged-timeline
    presence, and integrity status so the playback startup UI can sort runs and
    render compact labels, subtitles, and tooltips without reopening files.
    """

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
        """Return the descending sort key used for playback run discovery.

        Returns:
            A tuple of ``(unix_timestamp, run_id)`` when ``start_wall_time`` can
            be parsed, or ``(0, run_id)`` when no parseable start time is
            available.
        """
        parsed = _parse_iso_wall_time(self.start_wall_time)
        if parsed is None:
            return (0, self.run_id)
        return (int(parsed.timestamp()), self.run_id)

    @property
    def display_title(self) -> str:
        """Return the primary display label for the run list.

        Returns:
            ``"<run_id>  -  <test_name>"`` when a distinct test name is present,
            otherwise the run id alone.
        """
        test_name = (self.test_name or "").strip()
        if test_name and test_name != self.run_id:
            return f"{self.run_id}  -  {test_name}"
        return self.run_id

    @property
    def integrity_compact_label(self) -> str:
        """Return the compact archive-integrity label used in subtitles.

        Returns:
            A short ``archive=...`` label derived from the integrity badge or
            status.
        """
        if self.integrity_badge == "green":
            return "archive=ok"
        if self.integrity_badge == "yellow":
            return "archive=check"
        if self.integrity_badge == "red":
            return "archive=mismatch"
        return f"archive={self.integrity_status or 'unknown'}"

    @property
    def display_subtitle(self) -> str:
        """Build the one-line playback summary shown under the title.

        Returns:
            A pipe-delimited summary of mode, status, operator/profile metadata,
            wall-clock bounds, snapshot and merged-timeline availability, and
            integrity status.
        """
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
        """Build the multi-line tooltip text for playback run selection.

        Returns:
            A newline-delimited tooltip containing run identity, archive paths,
            operator and profile metadata, timing fields, snapshot and merged
            status, integrity details, and optional notes.
        """
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
    """Discover playback-ready runs under the project history root.

    The scan looks for run directories under ``ignitionhistory`` that contain a
    ``metadata.json`` file. Each discovered run is summarized with metadata,
    snapshot count, merged timeline presence, and optional integrity details.

    Args:
        project_root: Project root that contains the playback history root.
        include_integrity: Whether to load or compute integrity report data for
            each discovered run.

    Returns:
        Playback run summaries sorted newest-first by parsed start wall time and
        then by run id.
    """
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
        snapshot_count = (
            len(list(snapshots_dir.glob("*.json"))) if snapshots_dir.is_dir() else 0
        )
        integrity_report: dict[str, Any] | None = None
        integrity_report_path: Path | None = None
        integrity_status = "unknown"
        integrity_badge = "red"
        integrity_summary_message = "Integrity details unavailable."

        if include_integrity:
            integrity_report_path = child / INTEGRITY_REPORT_FILENAME
            integrity_report = _load_integrity_report_if_present(integrity_report_path)
            if integrity_report is None:
                integrity_report = _scan_integrity_report(
                    child, project_root=project_root_path
                )
            if isinstance(integrity_report, dict):
                integrity_status = (
                    _coerce_optional_str(integrity_report.get("overall_status"))
                    or "unknown"
                )
                integrity_badge = (
                    _coerce_optional_str(integrity_report.get("badge")) or "red"
                )
                integrity_summary_message = (
                    _coerce_optional_str(integrity_report.get("summary_message"))
                    or "Integrity details unavailable."
                )
                if (
                    integrity_report_path is not None
                    and not integrity_report_path.is_file()
                ):
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
    """Load run metadata from a playback run directory.

    Args:
        path: Path to the run's ``metadata.json`` file.

    Returns:
        The decoded metadata object.

    Raises:
        ValueError: If the decoded JSON value is not an object.
        OSError: If the file cannot be opened.
        json.JSONDecodeError: If the file does not contain valid JSON.
    """
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _load_integrity_report_if_present(path: Path) -> dict[str, Any] | None:
    """Load a persisted integrity report when one is present and valid.

    Args:
        path: Candidate integrity report path.

    Returns:
        The decoded integrity report object, or None when the file is missing,
        unreadable, invalid JSON, or not a JSON object.
    """
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _scan_integrity_report(
    run_dir: Path, *, project_root: Path
) -> dict[str, Any] | None:
    """Scan a run directory to compute integrity details on demand.

    Args:
        run_dir: Run directory to scan.
        project_root: Project root used by the integrity scanner.

    Returns:
        The computed integrity report object, or None when scanning fails or
        does not return a JSON object.
    """
    try:
        report = scan_run_integrity(run_dir, project_root=project_root)
    except Exception:
        return None
    return report if isinstance(report, dict) else None


def _coerce_optional_str(value: Any) -> str | None:
    """Normalize an optional string field loaded from JSON.

    Args:
        value: Value to normalize.

    Returns:
        The stripped string value, or None when the value is not a string or is
        empty after trimming whitespace.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _parse_iso_wall_time(value: str | None) -> datetime | None:
    """Parse an ISO wall-clock timestamp used by playback metadata.

    Args:
        value: Timestamp string that may end with ``Z``.

    Returns:
        A ``datetime`` parsed with timezone information when the value is
        present and valid, otherwise None.
    """
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
