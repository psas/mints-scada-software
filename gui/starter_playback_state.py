# gui/starter_playback_state.py

"""Starter playback-state models used during the playback refactor.

This module defines a minimal playback run context and a lightweight playback
state manager that own the current playback position and basic play/pause
state before the full playback wiring is moved over from the existing
window-host seek path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class PlaybackRunContext:
    """Describe the loaded playback run and its precomputed playback artifacts.

    Attributes:
        run_id: Archive run identifier for the loaded playback session.
        start_dt: Wall-clock timestamp for the start of the recorded run.
        end_dt: Wall-clock timestamp for the end of the recorded run.
        duration_seconds: Total playback duration in seconds.
        snapshot_index: Snapshot metadata used to seek into reconstructed state.
        merged_events: Structured merged events for the loaded run.
        event_time_keys: Playback-relative event timestamps aligned with
            ``merged_events``.
    """

    run_id: str
    start_dt: datetime
    end_dt: datetime
    duration_seconds: float
    snapshot_index: list[dict[str, Any]] = field(default_factory=list)
    merged_events: list[dict[str, Any]] = field(default_factory=list)
    event_time_keys: list[float] = field(default_factory=list)


class PlaybackStateManager:
    """Own starter playback position and play-state for a loaded run context.

    This scaffold is intentionally small. It tracks the active playback
    context, current playback position, last applied event index, and whether
    playback is currently running, but it does not yet replace the existing
    window-host seek and reconstruction flow.
    """

    def __init__(self) -> None:
        """Initialize the starter playback state with no loaded run."""
        self.context: PlaybackRunContext | None = None
        self.position_seconds: float = 0.0
        self.last_event_index: int = 0
        self.is_playing: bool = False

    def load_context(self, context: PlaybackRunContext) -> None:
        """Load a playback run context and reset transient playback state.

        Args:
            context: Playback run context that becomes the active playback
                source.

        Returns:
            None.
        """
        self.context = context
        self.position_seconds = 0.0
        self.last_event_index = 0
        self.is_playing = False

    def set_position(self, seconds: float) -> None:
        """Set the playback position in seconds from the start of the run.

        The stored position is clamped to zero so callers cannot move the
        playback cursor before the beginning of the loaded run.

        Args:
            seconds: Requested playback offset in seconds.

        Returns:
            None.
        """
        self.position_seconds = max(0.0, float(seconds))

    def mark_playing(self, playing: bool) -> None:
        """Update whether playback is currently advancing.

        Args:
            playing: True when playback should be treated as running.

        Returns:
            None.
        """
        self.is_playing = bool(playing)

    def wall_time_for_position(self, seconds: float | None = None) -> datetime | None:
        """Translate a playback offset into the run's wall-clock timestamp.

        Args:
            seconds: Optional playback offset in seconds. When omitted, the
                current stored playback position is used.

        Returns:
            The wall-clock timestamp for the requested playback position, or
            None when no playback context is loaded.
        """
        if self.context is None:
            return None
        value = self.position_seconds if seconds is None else max(0.0, float(seconds))
        return self.context.start_dt + timedelta(seconds=value)
