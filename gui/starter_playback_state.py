# gui/starter_playback_state.py

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class PlaybackRunContext:
    run_id: str
    start_dt: datetime
    end_dt: datetime
    duration_seconds: float
    snapshot_index: list[dict[str, Any]] = field(default_factory=list)
    merged_events: list[dict[str, Any]] = field(default_factory=list)
    event_time_keys: list[float] = field(default_factory=list)


class PlaybackStateManager:
    """
    Starter scaffold for the commit-5 refactor.

    Intent:
    - own playback position
    - own reconstructed state metadata
    - become the single authority that controller/scada/graph/timeline observe

    This starter does NOT replace your current window_host seek code yet.
    It is meant to be introduced first, then progressively wired in.
    """

    def __init__(self) -> None:
        self.context: PlaybackRunContext | None = None
        self.position_seconds: float = 0.0
        self.last_event_index: int = 0
        self.is_playing: bool = False

    def load_context(self, context: PlaybackRunContext) -> None:
        self.context = context
        self.position_seconds = 0.0
        self.last_event_index = 0
        self.is_playing = False

    def set_position(self, seconds: float) -> None:
        self.position_seconds = max(0.0, float(seconds))

    def mark_playing(self, playing: bool) -> None:
        self.is_playing = bool(playing)

    def wall_time_for_position(self, seconds: float | None = None) -> datetime | None:
        if self.context is None:
            return None
        value = self.position_seconds if seconds is None else max(0.0, float(seconds))
        return self.context.start_dt + timedelta(seconds=value)
