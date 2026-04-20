"""gui/graph_data.py

Shared graph data models and channel-key helpers.

This module defines the small transport-agnostic record types used by live and
playback graph providers. It also provides helpers for building and splitting
the canonical ``device.field`` channel keys used across graph views.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Mapping


@dataclass(frozen=True, order=True)
class GraphSample:
    """Represent a single numeric sample that can be rendered in a graph.

    This is the common record shape for both live and playback graph data. It
    is intentionally compact so callers can create samples from live telemetry,
    command-derived state, or playback ignition history without depending on a
    transport-specific payload type.

    Attributes:
        timestamp: Sample time in seconds.
        channel_key: Canonical graph channel identifier, typically in
            ``device.field`` form.
        value: Numeric sample value.
        source: Origin label for the sample stream.
        display_name: Optional human-friendly channel label.
        unit: Optional engineering unit string.
        metadata: Optional caller-defined metadata attached to the sample.
    """

    timestamp: float
    channel_key: str
    value: float
    source: str = "unknown"
    display_name: str | None = None
    unit: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        """Validate and normalize the sample fields after dataclass creation.

        Returns:
            None.

        Raises:
            ValueError: If ``channel_key`` is empty, or if ``timestamp`` or
                ``value`` are not finite.
            TypeError: If ``metadata`` is not a mapping.
        """
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
        """Return the preferred display label for the sample's channel.

        Returns:
            ``display_name`` when present, otherwise ``channel_key``.
        """
        return self.display_name or self.channel_key


@dataclass(frozen=True)
class GraphChannelDescriptor:
    """Describe a graphable channel independently of any individual sample.

    Attributes:
        channel_key: Canonical graph channel identifier, typically in
            ``device.field`` form.
        display_name: Optional human-friendly channel label.
        unit: Optional engineering unit string.
        source: Origin label for the channel definition.
        metadata: Optional caller-defined metadata associated with the channel.
    """

    channel_key: str
    display_name: str | None = None
    unit: str | None = None
    source: str = "unknown"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate and normalize the channel descriptor fields.

        Returns:
            None.

        Raises:
            ValueError: If ``channel_key`` is empty.
            TypeError: If ``metadata`` is not a mapping.
        """
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
        """Return the preferred display label for the channel.

        Returns:
            ``display_name`` when present, otherwise ``channel_key``.
        """
        return self.display_name or self.channel_key


@dataclass(frozen=True)
class GraphWindow:
    """Represent a requested graph time window in wall-clock seconds.

    Attributes:
        start_ts: Inclusive window start time in seconds, or None for an
            unbounded start.
        end_ts: Inclusive window end time in seconds, or None for an unbounded
            end.
    """

    start_ts: float | None = None
    end_ts: float | None = None

    def __post_init__(self) -> None:
        """Validate and normalize the window bounds.

        Returns:
            None.

        Raises:
            ValueError: If a provided bound is not finite, or if ``start_ts`` is
                greater than ``end_ts``.
        """
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
    """Build the canonical graph channel key for a device field.

    Args:
        device_id: Device identifier portion of the key.
        field_name: Field name portion of the key.

    Returns:
        The canonical ``device.field`` channel key.

    Raises:
        ValueError: If ``device_id`` or ``field_name`` is empty after stripping.
    """
    device = str(device_id or "").strip()
    field = str(field_name or "").strip()
    if not device:
        raise ValueError("device_id must be non-empty")
    if not field:
        raise ValueError("field_name must be non-empty")
    return f"{device}.{field}"


def split_channel_key(channel_key: str) -> tuple[str, str | None]:
    """Split a canonical graph channel key into device and field parts.

    Args:
        channel_key: Channel key to split.

    Returns:
        A ``(device_id, field_name)`` tuple. When the key does not contain a
        dot, the second element is None.

    Raises:
        ValueError: If ``channel_key`` is empty after stripping.
    """
    text = str(channel_key or "").strip()
    if not text:
        raise ValueError("channel_key must be non-empty")
    if "." not in text:
        return text, None
    device_id, field_name = text.split(".", 1)
    return device_id, (field_name or None)
