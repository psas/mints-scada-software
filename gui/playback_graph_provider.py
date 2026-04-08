from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .graph_data import GraphChannelDescriptor, GraphSample
from .graph_provider import InMemoryGraphDataProvider


@dataclass(frozen=True)
class _PlaybackChannelMeta:
    device_id: str
    display_name: str | None = None
    unit: str | None = None


class PlaybackGraphDataProvider(InMemoryGraphDataProvider):
    """Playback graph provider backed by ignitionhistory artifacts.

    Commit 3 keeps the commit-1/2 foundation intact and adds a playback-only
    provider that reads merged ignitionhistory events into GraphSample rows.
    Timestamps are stored as playback-relative seconds so GraphView can render
    against the current playback time window.
    """

    NUMERIC_KEYS = (
        "runtime_value",
        "value",
        "feedback_value",
        "feedback_state",
        "state",
        "runtime_state",
    )
    TIME_KEYS = ("time", "runtime_time", "wall_time")

    def __init__(self) -> None:
        super().__init__(retention_seconds=None)
        self._channel_meta: dict[str, _PlaybackChannelMeta] = {}
        self._history_dir: Path | None = None
        self._run_id: str | None = None
        self._playback_source: str = "native"
        self._loaded = False
        self._playback_cursor: float | None = None

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def run_id(self) -> str | None:
        return self._run_id

    def load_from_payload(self, payload: Mapping[str, Any]) -> list[GraphSample]:
        if not isinstance(payload, Mapping):
            return []

        history_dir_value = payload.get("history_dir")
        if not isinstance(history_dir_value, str) or not history_dir_value.strip():
            return []

        history_dir = Path(history_dir_value)
        playback_source = str(payload.get("playback_source") or "native")
        self._history_dir = history_dir
        self._run_id = str(payload.get("run_id") or history_dir.name)
        self._playback_source = playback_source

        metadata = self._load_json(history_dir / "metadata.json")
        merged_path = history_dir / ("merged.rebuild.jsonl" if playback_source == "rebuild" else "merged.jsonl")
        snapshots_dir = history_dir / ("snapshots_rebuild" if playback_source == "rebuild" else "snapshots")

        self.clear()
        self._channel_meta.clear()
        self._register_snapshot_channels(snapshots_dir)
        samples = self._load_merged_samples(merged_path, metadata)
        self._loaded = True
        return self.ingest_samples(samples)

    @property
    def playback_cursor(self) -> float | None:
        """Current playback position in run-relative seconds.

        When set, ``get_samples`` will never return samples with a
        timestamp beyond this value, regardless of the caller-supplied
        ``end_ts``.  This ensures the graph cannot show data from
        "the future" relative to the current playback position.
        """
        return self._playback_cursor

    def set_playback_cursor(self, seconds: float | None) -> None:
        """Set the playback cursor (run-relative seconds).

        Pass *None* to remove the ceiling (e.g. when leaving playback).
        """
        self._playback_cursor = None if seconds is None else max(0.0, float(seconds))

    def get_samples(
        self,
        *,
        channel_keys: Sequence[str] | None = None,
        start_ts: float | None = None,
        end_ts: float | None = None,
    ) -> list[GraphSample]:
        if self._playback_cursor is not None:
            if end_ts is None:
                end_ts = self._playback_cursor
            else:
                end_ts = min(float(end_ts), self._playback_cursor)
        return super().get_samples(
            channel_keys=channel_keys,
            start_ts=start_ts,
            end_ts=end_ts,
        )

    def get_channel_descriptors(self) -> list[GraphChannelDescriptor]:
        return super().get_channel_descriptors()

    def reset_run(self) -> None:
        self.clear()
        self._channel_meta.clear()
        self._history_dir = None
        self._run_id = None
        self._playback_source = "native"
        self._loaded = False
        self._playback_cursor = None

    def _register_snapshot_channels(self, snapshots_dir: Path) -> None:
        if not snapshots_dir.is_dir():
            return
        snapshot_files = sorted(snapshots_dir.glob('*.json'))
        if not snapshot_files:
            return
        try:
            payload = self._load_json(snapshot_files[0])
        except Exception:
            return
        state = payload.get('state') if isinstance(payload.get('state'), Mapping) else payload
        device_registry = state.get('device_registry') if isinstance(state, Mapping) else None
        devices = device_registry.get('devices', []) if isinstance(device_registry, Mapping) else []
        if not isinstance(devices, list):
            return
        for entry in devices:
            if not isinstance(entry, Mapping):
                continue
            device_id = str(entry.get('id') or '').strip()
            if not device_id:
                continue
            meta = _PlaybackChannelMeta(
                device_id=device_id,
                display_name=str(entry.get('name')) if isinstance(entry.get('name'), str) and entry.get('name').strip() else None,
                unit=str(entry.get('unit')) if isinstance(entry.get('unit'), str) and entry.get('unit').strip() else None,
            )
            self._channel_meta[device_id] = meta
            self.register_channel(GraphChannelDescriptor(
                channel_key=device_id,
                display_name=meta.display_name,
                unit=meta.unit,
                source='playback',
                metadata={'device_id': device_id},
            ))

    def _load_merged_samples(self, merged_path: Path, metadata: Mapping[str, Any]) -> list[GraphSample]:
        if not merged_path.exists():
            return []
        start_dt = self._parse_iso_dt(metadata.get('start_wall_time'))
        lines = merged_path.read_text(encoding='utf-8').splitlines()
        samples: list[GraphSample] = []
        first_event_dt: datetime | None = None
        for line in lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_dt = self._extract_event_dt(event)
            if first_event_dt is None and event_dt is not None:
                first_event_dt = event_dt
            relative_ts = self._relative_seconds(event_dt, start_dt or first_event_dt)
            if relative_ts is None:
                relative_ts = 0.0
            samples.extend(self._extract_samples_from_event(event, relative_ts))
        return samples

    def _extract_samples_from_event(self, event: Mapping[str, Any], relative_ts: float) -> list[GraphSample]:
        samples: list[GraphSample] = []

        telemetry = event.get('telemetry')
        if isinstance(telemetry, Mapping):
            for device_id, reading in telemetry.items():
                sample = self._build_sample(
                    device_id=device_id,
                    payload=reading,
                    default_ts=relative_ts,
                    source='playback_telemetry',
                )
                if sample is not None:
                    samples.append(sample)

        device_runtime = event.get('device_runtime')
        by_id = device_runtime.get('by_id') if isinstance(device_runtime, Mapping) else None
        if isinstance(by_id, Mapping):
            for device_id, runtime_state in by_id.items():
                sample = self._build_sample(
                    device_id=device_id,
                    payload=runtime_state,
                    default_ts=relative_ts,
                    source='playback_runtime',
                )
                if sample is not None:
                    samples.append(sample)

        return samples

    def _build_sample(self, *, device_id: Any, payload: Any, default_ts: float, source: str) -> GraphSample | None:
        device_text = str(device_id or '').strip()
        if not device_text:
            return None
        value = self._extract_numeric_value(payload)
        if value is None:
            return None
        sample_ts = default_ts
        if isinstance(payload, Mapping):
            for key in self.TIME_KEYS:
                parsed = self._coerce_relative_timestamp(payload.get(key), default_ts)
                if parsed is not None:
                    sample_ts = parsed
                    break
        meta = self._channel_meta.get(device_text)
        if meta is None:
            meta = _PlaybackChannelMeta(device_id=device_text)
            self._channel_meta[device_text] = meta
            self.register_channel(GraphChannelDescriptor(
                channel_key=device_text,
                display_name=None,
                unit=None,
                source='playback',
                metadata={'device_id': device_text},
            ))
        return GraphSample(
            timestamp=sample_ts,
            channel_key=device_text,
            value=value,
            source=source,
            display_name=meta.display_name,
            unit=meta.unit,
        )

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
            if text.lower() in {'open', 'opened', 'on', 'true'}:
                return 1.0
            if text.lower() in {'closed', 'close', 'off', 'false'}:
                return 0.0
            try:
                return float(text)
            except ValueError:
                return None
        return None

    @classmethod
    def _coerce_relative_timestamp(cls, value: Any, default_ts: float) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            numeric = float(value)
            if numeric >= 0.0 and numeric <= 1e6:
                return numeric
            return default_ts
        if isinstance(value, datetime):
            return default_ts
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                numeric = float(text)
                if numeric >= 0.0 and numeric <= 1e6:
                    return numeric
                return default_ts
            except ValueError:
                return default_ts
        return None

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding='utf-8'))

    @staticmethod
    def _parse_iso_dt(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        text = value.strip().replace('Z', '+00:00')
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @classmethod
    def _extract_event_dt(cls, event: Mapping[str, Any]) -> datetime | None:
        for key in ('wall_time', 'recorded_at', 'time'):
            dt = cls._parse_iso_dt(event.get(key))
            if dt is not None:
                return dt
        return None

    @staticmethod
    def _relative_seconds(event_dt: datetime | None, start_dt: datetime | None) -> float | None:
        if event_dt is None or start_dt is None:
            return None
        return max(0.0, (event_dt - start_dt).total_seconds())
