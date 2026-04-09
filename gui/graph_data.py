# gui/graph_data.py

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Mapping


@dataclass(frozen=True, order=True)
class GraphSample:
    """A single numeric sample that can be rendered in a graph.

    This is the common record shape for both live and playback graph data.
    It is intentionally tiny and transport-agnostic so it can be created from
    live telemetry, command-derived state, or playback ignition history.
    """

    timestamp: float
    channel_key: str
    value: float
    source: str = "unknown"
    display_name: str | None = None
    unit: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if not self.channel_key or not str(self.channel_key).strip():
            raise ValueError("channel_key must be a non-empty string")
        if not isfinite(float(self.timestamp)):
            raise ValueError("timestamp must be finite")
        if not isfinite(float(self.value)):
            raise ValueError("value must be finite")
        object.__setattr__(self, "timestamp", float(self.timestamp))
        object.__setattr__(self, "channel_key", str(self.channel_key))
        object.__setattr__(self, "value", float(self.value))
        object.__setattr__(self, "source", str(self.source or "unknown"))
        if self.display_name is not None:
            object.__setattr__(self, "display_name", str(self.display_name))
        if self.unit is not None:
            object.__setattr__(self, "unit", str(self.unit))
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")

    @property
    def label(self) -> str:
        return self.display_name or self.channel_key


@dataclass(frozen=True)
class GraphChannelDescriptor:
    """Metadata for a graphable channel."""

    channel_key: str
    display_name: str | None = None
    unit: str | None = None
    source: str = "unknown"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.channel_key or not str(self.channel_key).strip():
            raise ValueError("channel_key must be a non-empty string")
        object.__setattr__(self, "channel_key", str(self.channel_key))
        object.__setattr__(self, "source", str(self.source or "unknown"))
        if self.display_name is not None:
            object.__setattr__(self, "display_name", str(self.display_name))
        if self.unit is not None:
            object.__setattr__(self, "unit", str(self.unit))
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")

    @property
    def label(self) -> str:
        return self.display_name or self.channel_key


@dataclass(frozen=True)
class GraphWindow:
    """A requested graph time window in wall-clock seconds."""

    start_ts: float | None = None
    end_ts: float | None = None

    def __post_init__(self) -> None:
        start = None if self.start_ts is None else float(self.start_ts)
        end = None if self.end_ts is None else float(self.end_ts)
        if start is not None and not isfinite(start):
            raise ValueError("start_ts must be finite when provided")
        if end is not None and not isfinite(end):
            raise ValueError("end_ts must be finite when provided")
        if start is not None and end is not None and start > end:
            raise ValueError("start_ts must be <= end_ts")
        object.__setattr__(self, "start_ts", start)
        object.__setattr__(self, "end_ts", end)


def build_channel_key(device_id: str, field_name: str) -> str:
    device = str(device_id or "").strip()
    field = str(field_name or "").strip()
    if not device:
        raise ValueError("device_id must be non-empty")
    if not field:
        raise ValueError("field_name must be non-empty")
    return f"{device}.{field}"


def split_channel_key(channel_key: str) -> tuple[str, str | None]:
    text = str(channel_key or "").strip()
    if not text:
        raise ValueError("channel_key must be non-empty")
    if "." not in text:
        return text, None
    device_id, field_name = text.split(".", 1)
    return device_id, (field_name or None)
