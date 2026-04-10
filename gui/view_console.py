# gui/view_console.py

"""Console view helpers for live logging and playback event replay.

This module provides the console widget used by the GUI in two modes. In live
mode it wraps a ``QLoggingHandler`` widget for runtime log output. In playback
mode it loads archived console-style events from ``ignitionhistory`` and
renders the lines that are visible at the current playback time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from PyQt5.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from gui import QLoggingHandler


HISTORY_ROOT_DIRNAME = "ignitionhistory"
PLAYBACK_CONSOLE_STREAMS = ("system_event", "operator_action", "command_out")


@dataclass(frozen=True)
class PlaybackConsoleEntry:
    """Playback console line paired with its playback-relative timestamp.

    Attributes:
        rel_seconds: Playback-relative time in seconds when the line becomes
            visible.
        text: Rendered console line shown once playback reaches ``rel_seconds``.
    """

    rel_seconds: float
    text: str


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp string into a ``datetime``.

    Args:
        value: Candidate timestamp value.

    Returns:
        A parsed ``datetime`` when ``value`` is a non-empty ISO-8601 string, or
        None when parsing fails.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return datetime.fromisoformat(stripped.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    """Yield dictionary payloads from a JSONL file.

    Invalid JSON lines and non-dictionary payloads are ignored so playback can
    continue past malformed archive entries.

    Args:
        path: JSONL file to read.

    Yields:
        Parsed dictionary payloads from non-empty lines in the file.
    """
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                yield payload


def _format_rel_time(seconds: float) -> str:
    """Format playback-relative seconds as ``MM:SS.mmm``.

    Args:
        seconds: Playback-relative time in seconds.

    Returns:
        The formatted playback-relative timestamp string.
    """
    total_ms = max(0, int(round(float(seconds) * 1000.0)))
    minutes, rem_ms = divmod(total_ms, 60_000)
    seconds_whole, millis = divmod(rem_ms, 1000)
    return f"{minutes:02d}:{seconds_whole:02d}.{millis:03d}"


def _pick_event_wall_time(event: dict[str, Any]) -> datetime | None:
    """Return the first usable wall-clock timestamp from an archived event.

    The lookup prefers the canonical recorded/observed timestamp fields used by
    structured history and playback artifacts.

    Args:
        event: Archived event payload.

    Returns:
        The first parsed timestamp found in the known event time fields, or
        None when the event does not expose one.
    """
    for key in (
        "recorded_at",
        "wall_time",
        "operator_action_at",
        "observed_at",
        "structured_at",
    ):
        parsed = _parse_iso(event.get(key))
        if parsed is not None:
            return parsed
    return None


def _summarize_payload(event: dict[str, Any], excluded: set[str]) -> str:
    """Build a compact key-value summary from scalar event fields.

    Args:
        event: Event payload to summarize.
        excluded: Keys that should not appear in the summary.

    Returns:
        A pipe-delimited summary string built from up to four scalar fields that
        are not excluded and are not empty.
    """
    parts: list[str] = []
    for key, value in event.items():
        if key in excluded or value in (None, "", [], {}):
            continue
        if isinstance(value, (dict, list)):
            continue
        parts.append(f"{key}={value}")
        if len(parts) >= 4:
            break
    return " | ".join(parts)


def _format_playback_entry(event: dict[str, Any], rel_seconds: float) -> str:
    """Format one archived event as a console-style playback line.

    The formatter applies stream-specific summaries for ``system_event``,
    ``operator_action``, and ``command_out`` so the playback console mirrors
    the kinds of lines an operator would expect to see in the live console.

    Args:
        event: Archived event payload.
        rel_seconds: Playback-relative timestamp for the entry.

    Returns:
        The formatted console line for the event.
    """
    stream = str(event.get("stream") or event.get("event_kind") or "event")
    prefix = f"[{_format_rel_time(rel_seconds)}]"

    if stream == "system_event":
        severity = str(event.get("severity") or "info").upper()
        event_type = str(event.get("event_type") or "system_event")
        summary = _summarize_payload(
            event,
            {
                "run_id",
                "stream",
                "event_kind",
                "event_type",
                "severity",
                "recorded_at",
                "structured_at",
                "wall_time",
                "event_uid",
                "stream_seq",
                "canonical_hash",
                "recorded_by",
            },
        )
        return f"{prefix} {severity} {event_type}" + (
            f" | {summary}" if summary else ""
        )

    if stream == "operator_action":
        action = str(event.get("action") or "operator_action")
        summary = _summarize_payload(
            event,
            {
                "run_id",
                "stream",
                "event_kind",
                "action",
                "recorded_at",
                "structured_at",
                "operator_action_at",
                "event_uid",
                "stream_seq",
                "canonical_hash",
                "recorded_by",
            },
        )
        return f"{prefix} ACTION {action}" + (f" | {summary}" if summary else "")

    if stream == "command_out":
        command_name = str(
            event.get("command_name") or event.get("action") or "command_out"
        )
        device_id = event.get("device_id")
        result_summary = event.get("result_summary")
        tail: list[str] = []
        if device_id not in (None, ""):
            tail.append(f"device={device_id}")
        if result_summary not in (None, ""):
            tail.append(f"result={result_summary}")
        extra = _summarize_payload(
            event,
            {
                "run_id",
                "stream",
                "event_kind",
                "command_name",
                "action",
                "device_id",
                "result_summary",
                "recorded_at",
                "structured_at",
                "event_uid",
                "stream_seq",
                "canonical_hash",
            },
        )
        if extra:
            tail.append(extra)
        return f"{prefix} COMMAND {command_name}" + (
            f" | {' | '.join(tail)}" if tail else ""
        )

    semantic = event.get("semantic")
    if isinstance(semantic, dict):
        summary = semantic.get("summary")
        if isinstance(summary, str) and summary.strip():
            return f"{prefix} TELEMETRY {summary.strip()}"

    fallback = _summarize_payload(
        event,
        {
            "run_id",
            "stream",
            "event_kind",
            "recorded_at",
            "structured_at",
            "event_uid",
            "stream_seq",
            "canonical_hash",
        },
    )
    return f"{prefix} {stream}" + (f" | {fallback}" if fallback else "")


class ConsoleView(QWidget):
    """Console widget for live logging and playback log reconstruction.

    In live mode the view displays the widget exposed by ``QLoggingHandler``.
    In playback mode it loads archived console-style events from an
    ``ignitionhistory`` run directory and reveals lines as playback time
    advances.
    """

    def __init__(
        self,
        loghandler: QLoggingHandler | None,
        *,
        playback_mode: bool = False,
        project_root: str | Path | None = None,
    ):
        """Initialize the console view.

        Args:
            loghandler: Live logging handler whose widget should be embedded
                when not in playback mode. Ignored in playback mode.
            playback_mode: Whether the console should run in playback mode.
            project_root: Project root used to resolve ``ignitionhistory`` when
                playback runs are loaded by run ID.
        """
        super().__init__()
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.playback_mode = bool(playback_mode)
        self.project_root = (
            Path(project_root).expanduser().resolve()
            if project_root
            else Path(__file__).resolve().parents[1]
        )

        self.loghandler = (
            None if self.playback_mode else (loghandler or QLoggingHandler())
        )
        self._widget = (
            self.loghandler.widget if self.loghandler is not None else QPlainTextEdit()
        )
        self._widget.setReadOnly(True)
        self._widget.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.layout.addWidget(self._widget)

        self._playback_entries: list[PlaybackConsoleEntry] = []
        self._loaded_run_id: str | None = None
        self._current_playback_time = 0.0

        if self.playback_mode:
            self._widget.setPlainText(
                "Playback log ready. Load a run to replay archived events."
            )

    @property
    def widget(self):
        """Return the underlying text widget displayed by the view.

        Returns:
            The live logging widget or playback text widget used by the view.
        """
        return self._widget

    def clear_playback(self) -> None:
        """Reset playback state and restore the default playback prompt.

        Returns:
            None.
        """
        if not self.playback_mode:
            return
        self._loaded_run_id = None
        self._playback_entries = []
        self._widget.setPlainText(
            "Playback log ready. Load a run to replay archived events."
        )

    def load_playback_run(
        self,
        *,
        run_id: str | None = None,
        run_dir: str | Path | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Load archived console entries for a playback run.

        The loader resolves a run directory from either ``run_dir`` or
        ``run_id``, reads metadata when available, then builds
        playback-relative console entries from ``merged.jsonl`` or the
        per-stream fallback files.

        Args:
            run_id: Run identifier used to resolve a directory under
                ``ignitionhistory`` when ``run_dir`` is not provided.
            run_dir: Explicit playback run directory.
            metadata: Optional run metadata dictionary. When omitted, metadata
                is loaded from ``metadata.json`` if present.

        Returns:
            None.
        """
        if not self.playback_mode:
            return

        resolved_run_dir = self._resolve_run_dir(run_id=run_id, run_dir=run_dir)
        if resolved_run_dir is None or not resolved_run_dir.is_dir():
            self.clear_playback()
            self._widget.setPlainText("Playback archive not found for this run.")
            return

        metadata_path = resolved_run_dir / "metadata.json"
        if metadata is None and metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception:
                metadata = None

        self._playback_entries = self._load_playback_entries(
            resolved_run_dir,
            metadata if isinstance(metadata, dict) else {},
        )
        self._loaded_run_id = run_id or resolved_run_dir.name
        self.set_playback_time(self._current_playback_time)

    def set_playback_time(self, seconds: float) -> None:
        """Render playback console lines visible at the requested time.

        Args:
            seconds: Playback-relative time in seconds.

        Returns:
            None.
        """
        if not self.playback_mode:
            return

        try:
            self._current_playback_time = max(0.0, float(seconds))
        except (TypeError, ValueError):
            self._current_playback_time = 0.0

        if not self._playback_entries:
            if self._loaded_run_id:
                self._widget.setPlainText(
                    "No archived console-style events were found in ignitionhistory for this run."
                )
            return

        visible_lines = [
            entry.text
            for entry in self._playback_entries
            if entry.rel_seconds <= self._current_playback_time + 1e-9
        ]
        self._widget.setPlainText("\n".join(visible_lines))
        scrollbar = self._widget.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _resolve_run_dir(
        self,
        *,
        run_id: str | None,
        run_dir: str | Path | None,
    ) -> Path | None:
        """Resolve the playback run directory from explicit or derived inputs.

        Args:
            run_id: Run identifier under ``ignitionhistory``.
            run_dir: Explicit run directory path.

        Returns:
            The resolved playback run directory when one exists, or None.
        """
        if run_dir is not None:
            path = Path(run_dir).expanduser().resolve()
            if path.is_dir():
                return path

        if isinstance(run_id, str) and run_id.strip():
            return (self.project_root / HISTORY_ROOT_DIRNAME / run_id.strip()).resolve()

        return None

    def _load_playback_entries(
        self,
        run_dir: Path,
        metadata: dict[str, Any],
    ) -> list[PlaybackConsoleEntry]:
        """Build playback console entries from archived run artifacts.

        The loader prefers ``merged.jsonl`` and falls back to the individual
        stream files listed in ``PLAYBACK_CONSOLE_STREAMS``. Relative times are
        derived from run metadata when a start wall time is available; otherwise
        the event order index is used as a fallback timeline.

        Args:
            run_dir: Playback run directory containing archived history files.
            metadata: Run metadata used to derive the playback start wall time.

        Returns:
            Playback console entries sorted by playback-relative time.
        """
        start_wall_time = _parse_iso(
            metadata.get("start_wall_time")
            or (metadata.get("clock_info") or {}).get("start_wall_time")
        )

        merged_path = run_dir / "merged.jsonl"
        raw_events: list[dict[str, Any]] = []

        if merged_path.is_file():
            raw_events.extend(
                event
                for event in _iter_jsonl(merged_path)
                if str(event.get("stream") or event.get("event_kind") or "")
                in PLAYBACK_CONSOLE_STREAMS
            )
        else:
            for stream_name in PLAYBACK_CONSOLE_STREAMS:
                stream_path = run_dir / f"{stream_name}.jsonl"
                if stream_path.is_file():
                    raw_events.extend(_iter_jsonl(stream_path))

        entries: list[PlaybackConsoleEntry] = []
        for index, event in enumerate(raw_events):
            event_time = _pick_event_wall_time(event)
            if start_wall_time is not None and event_time is not None:
                rel_seconds = max(0.0, (event_time - start_wall_time).total_seconds())
            else:
                rel_seconds = float(index)
            entries.append(
                PlaybackConsoleEntry(
                    rel_seconds=rel_seconds,
                    text=_format_playback_entry(event, rel_seconds),
                )
            )

        entries.sort(key=lambda entry: entry.rel_seconds)
        return entries
