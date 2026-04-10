# gui/playback_state_manager.py

"""GUI-side playback runtime state models and control helpers.

This module defines the loaded playback run context and the small runtime state
machine that tracks playback position, play/pause state, speed, and the most
recent reconstructed GUI-visible state.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class PlaybackRunContext:
    """Loaded playback artifacts for a single run.

    Instances are populated after playback discovery/loading and then treated as
    immutable context for GUI-side playback control and reconstruction.

    Attributes:
        run_id: Canonical run identifier for the loaded playback session.
        history_dir: Path to the run's history directory.
        playback_source: Source label describing which playback artifact set was
            loaded.
        metadata: Run metadata loaded alongside playback artifacts.
        start_dt: Absolute wall-clock start time of the run.
        end_dt: Absolute wall-clock end time of the run.
        duration_seconds: Total playback duration in seconds.
        snapshot_index: Indexed snapshot metadata used for nearest-snapshot
            lookup during seek/reconstruction.
        snapshot_files: Snapshot file paths available for the run.
        merged_events: Full merged event stream for the loaded run.
        seek_events: Event stream used for seek/replay reconstruction.
        event_time_keys: Sorted event-relative timestamps used for event index
            lookup.
        initial_snapshot: Optional initial snapshot baseline for playback
            reconstruction.
    """

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
    """Own GUI-side playback runtime state for the current loaded run.

    Owns:
        - Loaded run context metadata, events, and snapshots
        - Current playback position and event bookkeeping
        - Play/pause timing anchors and playback speed
        - The most recent reconstructed playback-visible state snapshot

    Does not own:
        - File I/O for playback artifacts
        - Widget or display updates
        - Applying snapshots into the device catalog or window state
    """

    SPEED_STEPS = (0.25, 0.5, 1.0, 2.0, 4.0)

    def __init__(self) -> None:
        """Initialize an empty playback runtime state manager."""
        self.context: PlaybackRunContext | None = None
        self.position_seconds: float = 0.0
        self.last_event_index: int = 0
        self.last_applied_time: float = 0.0
        self.is_playing: bool = False
        self.speed: float = 1.0
        self._anchor: float = 0.0
        self._mono_start: float = 0.0
        self.reconstructed_state: dict[str, Any] | None = None

    def load_context(self, context: PlaybackRunContext) -> None:
        """Load a playback run context and reset runtime playback state.

        Args:
            context: Loaded playback artifacts and metadata for the selected
                run.

        Returns:
            None.
        """
        self.context = context
        self.position_seconds = 0.0
        self.last_event_index = 0
        self.last_applied_time = 0.0
        self.is_playing = False
        self.speed = 1.0
        self._anchor = 0.0
        self._mono_start = 0.0
        self.reconstructed_state = None

    # -- Convenience properties for context access --

    @property
    def duration_seconds(self) -> float:
        """Return the loaded playback duration in seconds."""
        return self.context.duration_seconds if self.context else 0.0

    @property
    def start_dt(self) -> datetime | None:
        """Return the loaded run start time, if a context is loaded."""
        return self.context.start_dt if self.context else None

    @property
    def end_dt(self) -> datetime | None:
        """Return the loaded run end time, if a context is loaded."""
        return self.context.end_dt if self.context else None

    @property
    def snapshot_index(self) -> list[dict[str, Any]]:
        """Return the loaded snapshot index."""
        return self.context.snapshot_index if self.context else []

    @property
    def seek_events(self) -> list[dict[str, Any]]:
        """Return the event stream used for seek-time reconstruction."""
        return self.context.seek_events if self.context else []

    @property
    def event_time_keys(self) -> list[float]:
        """Return sorted relative event times for event-index lookup."""
        return self.context.event_time_keys if self.context else []

    @property
    def merged_events(self) -> list[dict[str, Any]]:
        """Return the full merged event stream for the loaded run."""
        return self.context.merged_events if self.context else []

    @property
    def run_id(self) -> str | None:
        """Return the loaded run identifier, if a context is loaded."""
        return self.context.run_id if self.context else None

    # -- Position control --

    def set_position(self, seconds: float) -> None:
        """Set the playback position, clamped to zero or greater.

        Args:
            seconds: Requested playback position in seconds.

        Returns:
            None.
        """
        self.position_seconds = max(0.0, float(seconds))

    def update_after_seek(self, *, position: float, event_index: int) -> None:
        """Store playback bookkeeping after a seek operation completes.

        Args:
            position: Playback position reached by the seek operation.
            event_index: Index of the last event considered applied at the new
                position.

        Returns:
            None.
        """
        self.position_seconds = max(0.0, float(position))
        self.last_event_index = int(event_index)
        self.last_applied_time = self.position_seconds

    def update_after_advance(self, *, position: float, event_index: int) -> None:
        """Store playback bookkeeping after normal playback advancement.

        Args:
            position: Playback position reached after advancing.
            event_index: Index of the last event considered applied at the new
                position.

        Returns:
            None.
        """
        self.position_seconds = max(0.0, float(position))
        self.last_event_index = int(event_index)
        self.last_applied_time = self.position_seconds

    # -- Playback engine control --

    def start_playing(self) -> bool:
        """Begin playback from the current position.

        Returns:
            True when playback is active or successfully started. False when the
            current position is already at the end of a non-empty run.
        """
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
        """Pause playback and persist the exact computed playback position.

        Returns:
            The playback position in seconds at the moment playback was paused.
        """
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
        """Toggle playback between playing and paused states.

        Returns:
            The new ``is_playing`` state after toggling.
        """
        if self.is_playing:
            self.pause()
            return False
        return self.start_playing()

    def compute_advance_time(self) -> float:
        """Compute the current playback position from the monotonic clock.

        Returns:
            The current playback position in seconds, clamped to the loaded run
            duration when one exists.
        """
        if not self.is_playing:
            return self.position_seconds
        elapsed = time.monotonic() - self._mono_start
        new_time = self._anchor + (elapsed * self.speed)
        duration = self.duration_seconds
        if duration > 0:
            new_time = min(new_time, duration)
        return max(0.0, new_time)

    def at_end(self) -> bool:
        """Return whether playback has reached the end of the loaded run.

        Returns:
            True when a non-empty run is loaded and the current position is at
            or beyond its duration. False otherwise.
        """
        duration = self.duration_seconds
        if duration <= 0:
            return False
        return self.position_seconds >= duration

    def set_speed(self, speed: float) -> None:
        """Set playback speed and re-anchor timing if playback is active.

        Args:
            speed: Requested playback speed multiplier.

        Returns:
            None.
        """
        if self.is_playing:
            self.position_seconds = self.compute_advance_time()
            self._anchor = self.position_seconds
            self._mono_start = time.monotonic()
        self.speed = max(0.01, float(speed))

    def step_speed(self, direction: int) -> float:
        """Move to the next configured playback speed step.

        Args:
            direction: Step direction. Positive values move forward through
                ``SPEED_STEPS`` and negative values move backward.

        Returns:
            The new playback speed.
        """
        steps = list(self.SPEED_STEPS)
        try:
            current_index = steps.index(self.speed)
        except ValueError:
            current_index = steps.index(1.0) if 1.0 in steps else 0
        next_index = min(max(current_index + int(direction), 0), len(steps) - 1)
        self.set_speed(steps[next_index])
        return self.speed

    # -- Reconstructed state --

    def update_reconstructed_state(self, state: dict[str, Any]) -> None:
        """Store the reconstructed playback-visible state for the current position.

        This is called after snapshot restore and tail replay have completed for
        the current position. The stored mapping is copied so later callers do
        not mutate the manager's retained playback-visible state in place.

        Args:
            state: Reconstructed playback-visible state at the current
                position.

        Returns:
            None.
        """
        self.reconstructed_state = dict(state)

    # -- Utility --

    def wall_time_for_position(self, seconds: float | None = None) -> datetime | None:
        """Translate a playback-relative position into an absolute wall-clock time.

        Args:
            seconds: Optional playback-relative position in seconds. When not
                provided, the current playback position is used.

        Returns:
            The absolute wall-clock time for the requested playback position, or
            None when no playback context is loaded.
        """
        if self.context is None:
            return None
        value = self.position_seconds if seconds is None else max(0.0, float(seconds))
        return self.context.start_dt + timedelta(seconds=value)
