# gui/live_graph_provider.py

"""Live graph data provider backed by backend snapshots and structured events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
import time

from .graph_data import GraphChannelDescriptor, GraphSample
from .graph_provider import InMemoryGraphDataProvider


@dataclass(frozen=True)
class _LiveChannelMeta:
    """Presentation metadata tracked for a live graph channel.

    Args:
        device_id: Canonical device identifier used as the channel key.
        display_name: Optional display label derived from the backend device registry.
        unit: Optional engineering unit associated with the channel.
    """

    device_id: str
    display_name: str | None = None
    unit: str | None = None


class LiveGraphDataProvider(InMemoryGraphDataProvider):
    """In-memory live graph provider fed by backend snapshots and structured events.

    The provider stores numeric samples keyed by device id and registers channel
    metadata from backend device-registry snapshots so live graphs can reuse the
    same channel descriptors across snapshot and event-driven updates.
    """

    NUMERIC_KEYS = ("runtime_value", "value")
    TIME_KEYS = ("runtime_time", "time", "wall_time")

    def __init__(self, *, retention_seconds: float = 1800.0) -> None:
        """Initialize the live graph provider.

        Args:
            retention_seconds: Maximum sample age retained by the in-memory
                provider.
        """
        super().__init__(retention_seconds=retention_seconds)
        self._channel_meta: dict[str, _LiveChannelMeta] = {}

    def ingest_state_snapshot(self, snapshot: Mapping[str, Any]) -> list[GraphSample]:
        """Ingest graph samples from a backend full-state snapshot.

        The snapshot path registers channel metadata from ``device_registry`` and
        then extracts numeric runtime values from ``device_runtime.by_id``.

        Args:
            snapshot: Backend state snapshot.

        Returns:
            The samples accepted by ``ingest_samples``. Returns an empty list
            when ``snapshot`` is not a mapping or does not contain usable
            numeric runtime values.
        """
        if not isinstance(snapshot, Mapping):
            return []

        self._register_snapshot_channels(snapshot)
        timestamp_fallback = self._coerce_timestamp(snapshot.get("wall_time"))
        runtime_by_id = self._extract_runtime_by_id(snapshot)
        samples = self._build_runtime_samples(runtime_by_id, timestamp_fallback)
        return self.ingest_samples(samples)

    def ingest_structured_event(self, payload: Mapping[str, Any]) -> list[GraphSample]:
        """Ingest graph samples from a live structured event payload.

        This path reads telemetry values from the event's ``telemetry`` mapping
        and uses per-reading timestamps when available, otherwise falling back
        to the event wall time or the current clock time.

        Args:
            payload: Structured event payload emitted by the backend.

        Returns:
            The samples accepted by ``ingest_samples``. Returns an empty list
            when ``payload`` is not a mapping or does not contain usable
            telemetry readings.
        """
        if not isinstance(payload, Mapping):
            return []

        timestamp_fallback = self._coerce_timestamp(payload.get("wall_time"))
        telemetry = payload.get("telemetry")
        samples: list[GraphSample] = []
        if isinstance(telemetry, Mapping):
            for device_id, reading in telemetry.items():
                device_text = str(device_id or "").strip()
                if not device_text:
                    continue
                value = self._extract_numeric_value(reading)
                if value is None:
                    continue
                timestamp = timestamp_fallback
                if isinstance(reading, Mapping):
                    timestamp = (
                        self._coerce_timestamp(reading.get("time"))
                        or timestamp_fallback
                    )
                meta = self._channel_meta.get(device_text)
                samples.append(
                    GraphSample(
                        timestamp=timestamp or time.time(),
                        channel_key=device_text,
                        value=value,
                        source="live_structured_event",
                        display_name=meta.display_name if meta else None,
                        unit=meta.unit if meta else None,
                    )
                )
        return self.ingest_samples(samples)

    def _register_snapshot_channels(self, snapshot: Mapping[str, Any]) -> None:
        """Register channel descriptors from snapshot device-registry metadata.

        Args:
            snapshot: Backend state snapshot that may include
                ``device_registry.devices``.

        Returns:
            None.
        """
        device_registry = snapshot.get("device_registry")
        registry_devices = []
        if isinstance(device_registry, Mapping):
            registry_devices = device_registry.get("devices", [])
        if not isinstance(registry_devices, list):
            return
        for entry in registry_devices:
            if not isinstance(entry, Mapping):
                continue
            device_id = str(entry.get("id") or "").strip()
            if not device_id:
                continue
            display_name = entry.get("name")
            unit = entry.get("unit")
            self._channel_meta[device_id] = _LiveChannelMeta(
                device_id=device_id,
                display_name=(
                    str(display_name)
                    if isinstance(display_name, str) and display_name.strip()
                    else None
                ),
                unit=str(unit) if isinstance(unit, str) and unit.strip() else None,
            )
            self.register_channel(
                GraphChannelDescriptor(
                    channel_key=device_id,
                    display_name=self._channel_meta[device_id].display_name,
                    unit=self._channel_meta[device_id].unit,
                    source="live",
                    metadata={"device_id": device_id},
                )
            )

    def _build_runtime_samples(
        self,
        runtime_by_id: Mapping[str, Any],
        timestamp_fallback: float | None,
    ) -> list[GraphSample]:
        """Build graph samples from per-device runtime state.

        Args:
            runtime_by_id: Mapping of device id to runtime state payload.
            timestamp_fallback: Fallback timestamp used when a runtime entry
                does not include any recognized time key.

        Returns:
            Graph samples built from numeric runtime values found in
            ``runtime_by_id``.
        """
        samples: list[GraphSample] = []
        for device_id, runtime_state in runtime_by_id.items():
            device_text = str(device_id or "").strip()
            if not device_text or not isinstance(runtime_state, Mapping):
                continue
            value = self._extract_numeric_value(runtime_state)
            if value is None:
                continue
            timestamp = None
            for key in self.TIME_KEYS:
                timestamp = self._coerce_timestamp(runtime_state.get(key))
                if timestamp is not None:
                    break
            timestamp = timestamp if timestamp is not None else timestamp_fallback
            meta = self._channel_meta.get(device_text)
            samples.append(
                GraphSample(
                    timestamp=timestamp or time.time(),
                    channel_key=device_text,
                    value=value,
                    source="live_snapshot",
                    display_name=meta.display_name if meta else None,
                    unit=meta.unit if meta else None,
                )
            )
        return samples

    @staticmethod
    def _extract_runtime_by_id(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
        """Extract the ``device_runtime.by_id`` mapping from a backend snapshot.

        Args:
            snapshot: Backend state snapshot.

        Returns:
            The runtime mapping keyed by device id, or an empty mapping when the
            snapshot does not expose the expected structure.
        """
        device_runtime = snapshot.get("device_runtime")
        if not isinstance(device_runtime, Mapping):
            return {}
        by_id = device_runtime.get("by_id")
        return by_id if isinstance(by_id, Mapping) else {}

    @classmethod
    def _extract_numeric_value(cls, payload: Any) -> float | None:
        """Extract the first recognized numeric value from a payload.

        Mapping payloads are searched using ``NUMERIC_KEYS`` in order. Non-mapping
        payloads are coerced directly.

        Args:
            payload: Runtime or telemetry payload to inspect.

        Returns:
            The numeric value as a float, or None when the payload does not
            contain a recognized numeric value.
        """
        if isinstance(payload, Mapping):
            for key in cls.NUMERIC_KEYS:
                value = cls._coerce_numeric(payload.get(key))
                if value is not None:
                    return value
            return None
        return cls._coerce_numeric(payload)

    @staticmethod
    def _coerce_numeric(value: Any) -> float | None:
        """Coerce a runtime value into a float sample value.

        Booleans are mapped to ``1.0`` and ``0.0`` so logical state can still be
        graphed by numeric consumers.

        Args:
            value: Raw value to coerce.

        Returns:
            The coerced float value, or None when the value is empty or cannot
            be parsed as numeric.
        """
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return float(text)
            except ValueError:
                return None
        return None

    @staticmethod
    def _coerce_timestamp(value: Any) -> float | None:
        """Coerce a timestamp-like value into Unix seconds.

        Supported inputs are numeric epoch seconds, numeric strings, ISO 8601
        strings, and ``datetime`` objects. Naive datetimes are treated as UTC.

        Args:
            value: Raw timestamp value to coerce.

        Returns:
            The timestamp in Unix seconds, or None when the value cannot be
            interpreted as a supported timestamp representation.
        """
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return float(text)
            except ValueError:
                pass
            try:
                normalized = text.replace("Z", "+00:00")
                return datetime.fromisoformat(normalized).timestamp()
            except ValueError:
                return None
        if isinstance(value, datetime):
            dt = (
                value
                if value.tzinfo is not None
                else value.replace(tzinfo=timezone.utc)
            )
            return dt.timestamp()
        return None
