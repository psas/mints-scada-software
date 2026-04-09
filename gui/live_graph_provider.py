# gui/live_graph_provider.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
import time

from .graph_data import GraphChannelDescriptor, GraphSample
from .graph_provider import InMemoryGraphDataProvider


@dataclass(frozen=True)
class _LiveChannelMeta:
    device_id: str
    display_name: str | None = None
    unit: str | None = None


class LiveGraphDataProvider(InMemoryGraphDataProvider):
    """Live-only graph provider backed by backend snapshots/events.

    This keeps the commit-1 provider foundation and adapts the current
    backend-first architecture without redesigning the graph widget.
    The provider stores numeric samples keyed by device id.
    """

    NUMERIC_KEYS = ("runtime_value", "value")
    TIME_KEYS = ("runtime_time", "time", "wall_time")

    def __init__(self, *, retention_seconds: float = 1800.0) -> None:
        super().__init__(retention_seconds=retention_seconds)
        self._channel_meta: dict[str, _LiveChannelMeta] = {}

    def ingest_state_snapshot(self, snapshot: Mapping[str, Any]) -> list[GraphSample]:
        if not isinstance(snapshot, Mapping):
            return []

        self._register_snapshot_channels(snapshot)
        timestamp_fallback = self._coerce_timestamp(snapshot.get("wall_time"))
        runtime_by_id = self._extract_runtime_by_id(snapshot)
        samples = self._build_runtime_samples(runtime_by_id, timestamp_fallback)
        return self.ingest_samples(samples)

    def ingest_structured_event(self, payload: Mapping[str, Any]) -> list[GraphSample]:
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
                    timestamp = self._coerce_timestamp(reading.get("time")) or timestamp_fallback
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
                display_name=str(display_name) if isinstance(display_name, str) and display_name.strip() else None,
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
        device_runtime = snapshot.get("device_runtime")
        if not isinstance(device_runtime, Mapping):
            return {}
        by_id = device_runtime.get("by_id")
        return by_id if isinstance(by_id, Mapping) else {}

    @classmethod
    def _extract_numeric_value(cls, payload: Any) -> float | None:
        if isinstance(payload, Mapping):
            for key in cls.NUMERIC_KEYS:
                value = cls._coerce_numeric(payload.get(key))
                if value is not None:
                    return value
            return None
        return cls._coerce_numeric(payload)

    @staticmethod
    def _coerce_numeric(value: Any) -> float | None:
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
            dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        return None
