from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class PlaybackRunContext:
    """Loaded playback run artifacts. Treated as immutable after load."""

    run_id: str
    history_dir: str
    playback_source: str
    metadata: dict[str, Any]
    start_dt: datetime
    end_dt: datetime
    duration_seconds: float
    snapshot_index: list[dict[str, Any]] = field(default_factory=list)
    snapshot_files: list[str] = field(default_factory=list)
    merged_events: list[dict[str, Any]] = field(default_factory=list)
    seek_events: list[dict[str, Any]] = field(default_factory=list)
    event_time_keys: list[float] = field(default_factory=list)
    initial_snapshot: dict[str, Any] | None = None


class PlaybackStateManager:
    """Single authoritative owner of GUI-side playback runtime state.

    Owns:
      - Loaded run context (events, snapshots, metadata)
      - Current position and event bookkeeping
      - Play/pause engine state (anchor, speed, monotonic clock)

    Does NOT own:
      - File I/O (window_host handles loading)
      - Widget/display updates (controller/scada handle rendering)
      - Snapshot application to device catalog (window_host handles that)
    """

    SPEED_STEPS = (0.25, 0.5, 1.0, 2.0, 4.0)

    def __init__(self) -> None:
        self.context: PlaybackRunContext | None = None
        self.position_seconds: float = 0.0
        self.last_event_index: int = 0
        self.last_applied_time: float = 0.0
        self.is_playing: bool = False
        self.speed: float = 1.0
        self._anchor: float = 0.0
        self._mono_start: float = 0.0

    def load_context(self, context: PlaybackRunContext) -> None:
        """Load a run context and reset all runtime state to initial."""
        self.context = context
        self.position_seconds = 0.0
        self.last_event_index = 0
        self.last_applied_time = 0.0
        self.is_playing = False
        self.speed = 1.0
        self._anchor = 0.0
        self._mono_start = 0.0

    # -- Convenience properties for context access --

    @property
    def duration_seconds(self) -> float:
        return self.context.duration_seconds if self.context else 0.0

    @property
    def start_dt(self) -> datetime | None:
        return self.context.start_dt if self.context else None

    @property
    def end_dt(self) -> datetime | None:
        return self.context.end_dt if self.context else None

    @property
    def snapshot_index(self) -> list[dict[str, Any]]:
        return self.context.snapshot_index if self.context else []

    @property
    def seek_events(self) -> list[dict[str, Any]]:
        return self.context.seek_events if self.context else []

    @property
    def event_time_keys(self) -> list[float]:
        return self.context.event_time_keys if self.context else []

    @property
    def merged_events(self) -> list[dict[str, Any]]:
        return self.context.merged_events if self.context else []

    @property
    def run_id(self) -> str | None:
        return self.context.run_id if self.context else None

    # -- Position control --

    def set_position(self, seconds: float) -> None:
        self.position_seconds = max(0.0, float(seconds))

    def update_after_seek(self, *, position: float, event_index: int) -> None:
        self.position_seconds = max(0.0, float(position))
        self.last_event_index = int(event_index)
        self.last_applied_time = self.position_seconds

    def update_after_advance(self, *, position: float, event_index: int) -> None:
        self.position_seconds = max(0.0, float(position))
        self.last_event_index = int(event_index)
        self.last_applied_time = self.position_seconds

    # -- Playback engine control --

    def start_playing(self) -> bool:
        """Begin playback from current position. Returns False if at end."""
        if self.is_playing:
            return True
        duration = self.duration_seconds
        if duration > 0 and self.position_seconds >= duration:
            return False
        self._anchor = self.position_seconds
        self._mono_start = time.monotonic()
        self.is_playing = True
        return True

    def pause(self) -> float:
        """Pause playback. Returns the exact computed position."""
        if not self.is_playing:
            return self.position_seconds
        elapsed = time.monotonic() - self._mono_start
        exact = self._anchor + (elapsed * self.speed)
        duration = self.duration_seconds
        if duration > 0:
            exact = min(exact, duration)
        self.position_seconds = max(0.0, exact)
        self.is_playing = False
        return self.position_seconds

    def toggle_playing(self) -> bool:
        """Toggle play/pause. Returns new is_playing state."""
        if self.is_playing:
            self.pause()
            return False
        return self.start_playing()

    def compute_advance_time(self) -> float:
        """Compute current playback position from monotonic clock."""
        if not self.is_playing:
            return self.position_seconds
        elapsed = time.monotonic() - self._mono_start
        new_time = self._anchor + (elapsed * self.speed)
        duration = self.duration_seconds
        if duration > 0:
            new_time = min(new_time, duration)
        return max(0.0, new_time)

    def at_end(self) -> bool:
        """True if playback has reached or passed the end."""
        duration = self.duration_seconds
        if duration <= 0:
            return False
        return self.position_seconds >= duration

    def set_speed(self, speed: float) -> None:
        """Set playback speed. Re-anchors if currently playing."""
        if self.is_playing:
            self.position_seconds = self.compute_advance_time()
            self._anchor = self.position_seconds
            self._mono_start = time.monotonic()
        self.speed = max(0.01, float(speed))

    def step_speed(self, direction: int) -> float:
        """Step speed up (+1) or down (-1). Returns new speed."""
        steps = list(self.SPEED_STEPS)
        try:
            current_index = steps.index(self.speed)
        except ValueError:
            current_index = steps.index(1.0) if 1.0 in steps else 0
        next_index = min(max(current_index + int(direction), 0), len(steps) - 1)
        self.set_speed(steps[next_index])
        return self.speed

    # -- Utility --

    def wall_time_for_position(self, seconds: float | None = None) -> datetime | None:
        if self.context is None:
            return None
        value = self.position_seconds if seconds is None else max(0.0, float(seconds))
        return self.context.start_dt + timedelta(seconds=value)
