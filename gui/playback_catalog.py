from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

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

        if self.notes:
            lines.append("")
            lines.append(self.notes)

        return "\n".join(lines)


def discover_playback_runs(project_root: str | Path) -> list[PlaybackRunSummary]:
    history_root = Path(project_root).expanduser().resolve() / HISTORY_ROOT_DIRNAME
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
            # One malformed run should not hide the rest of the playback catalog.
            continue

        snapshots_dir = child / "snapshots"
        snapshot_count = len(list(snapshots_dir.glob("*.json"))) if snapshots_dir.is_dir() else 0

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
