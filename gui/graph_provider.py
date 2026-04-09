# gui/graph_provider.py

from __future__ import annotations

from abc import ABC, abstractmethod
from bisect import bisect_left, bisect_right
from collections import defaultdict
from typing import Callable, Iterable, Sequence

from .graph_data import GraphChannelDescriptor, GraphSample, GraphWindow

GraphSamplesListener = Callable[[list[GraphSample]], None]


class BaseGraphDataProvider(ABC):
    """Common interface for graph data sources.

    The provider is intentionally UI-agnostic:
    - live providers can subscribe to backend snapshots/events
    - playback providers can read ignition history
    - graph widgets can consume the same GraphSample records from either source
    """

    def __init__(self) -> None:
        self._running = False
        self._subscriptions: set[str] = set()
        self._window = GraphWindow()
        self._listeners: list[GraphSamplesListener] = []

    @property
    def running(self) -> bool:
        return self._running

    @property
    def subscriptions(self) -> tuple[str, ...]:
        return tuple(sorted(self._subscriptions))

    @property
    def window(self) -> GraphWindow:
        return self._window

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._on_start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._on_stop()

    def subscribe(self, channel_keys: Sequence[str]) -> None:
        normalized = {str(key).strip() for key in channel_keys if str(key).strip()}
        if not normalized:
            return
        self._subscriptions.update(normalized)
        self._on_subscription_changed()

    def unsubscribe(self, channel_keys: Sequence[str]) -> None:
        removed = False
        for key in channel_keys:
            text = str(key).strip()
            if text in self._subscriptions:
                self._subscriptions.remove(text)
                removed = True
        if removed:
            self._on_subscription_changed()

    def clear_subscriptions(self) -> None:
        if not self._subscriptions:
            return
        self._subscriptions.clear()
        self._on_subscription_changed()

    def set_time_window(self, *, start_ts: float | None = None, end_ts: float | None = None) -> None:
        self._window = GraphWindow(start_ts=start_ts, end_ts=end_ts)
        self._on_window_changed()

    def add_listener(self, callback: GraphSamplesListener) -> None:
        if callback in self._listeners:
            return
        self._listeners.append(callback)

    def remove_listener(self, callback: GraphSamplesListener) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _emit_samples(self, samples: Iterable[GraphSample]) -> None:
        payload = list(samples)
        if not payload:
            return
        for callback in list(self._listeners):
            callback(payload)

    def _on_start(self) -> None:
        pass

    def _on_stop(self) -> None:
        pass

    def _on_subscription_changed(self) -> None:
        pass

    def _on_window_changed(self) -> None:
        pass

    @abstractmethod
    def get_channel_descriptors(self) -> list[GraphChannelDescriptor]:
        raise NotImplementedError

    @abstractmethod
    def get_samples(
        self,
        *,
        channel_keys: Sequence[str] | None = None,
        start_ts: float | None = None,
        end_ts: float | None = None,
    ) -> list[GraphSample]:
        raise NotImplementedError


class InMemoryGraphDataProvider(BaseGraphDataProvider):
    """Small provider used as the commit-1 foundation.

    This can back tests immediately and later be reused by live/playback adapters.
    It stores GraphSample rows in-memory, supports subscriptions/windowing, and
    emits appended samples to listeners.
    """

    def __init__(self, *, retention_seconds: float | None = None) -> None:
        super().__init__()
        self._retention_seconds = None if retention_seconds is None else float(retention_seconds)
        self._samples_by_channel: dict[str, list[GraphSample]] = defaultdict(list)
        self._descriptors: dict[str, GraphChannelDescriptor] = {}

    def register_channel(self, descriptor: GraphChannelDescriptor) -> None:
        self._descriptors[descriptor.channel_key] = descriptor

    def register_channels(self, descriptors: Iterable[GraphChannelDescriptor]) -> None:
        for descriptor in descriptors:
            self.register_channel(descriptor)

    def get_channel_descriptors(self) -> list[GraphChannelDescriptor]:
        descriptors = list(self._descriptors.values())
        descriptors.sort(key=lambda item: item.channel_key)
        return descriptors

    def ingest_samples(self, samples: Iterable[GraphSample]) -> list[GraphSample]:
        payload = list(samples)
        if not payload:
            return []

        appended: list[GraphSample] = []
        for sample in payload:
            existing = self._samples_by_channel[sample.channel_key]
            idx = bisect_right([row.timestamp for row in existing], sample.timestamp)
            existing.insert(idx, sample)
            if sample.channel_key not in self._descriptors:
                self._descriptors[sample.channel_key] = GraphChannelDescriptor(
                    channel_key=sample.channel_key,
                    display_name=sample.display_name,
                    unit=sample.unit,
                    source=sample.source,
                    metadata=sample.metadata,
                )
            self._trim_channel(sample.channel_key)
            if (not self._subscriptions) or (sample.channel_key in self._subscriptions):
                if self._sample_in_window(sample, self._window.start_ts, self._window.end_ts):
                    appended.append(sample)

        self._emit_samples(appended)
        return appended

    def clear(self) -> None:
        self._samples_by_channel.clear()
        self._descriptors.clear()

    def list_channel_keys(self) -> list[str]:
        keys = set(self._samples_by_channel.keys()) | set(self._descriptors.keys())
        return sorted(keys)

    def get_samples(
        self,
        *,
        channel_keys: Sequence[str] | None = None,
        start_ts: float | None = None,
        end_ts: float | None = None,
    ) -> list[GraphSample]:
        requested_keys = self._resolve_requested_keys(channel_keys)
        lower = self._window.start_ts if start_ts is None else float(start_ts)
        upper = self._window.end_ts if end_ts is None else float(end_ts)

        results: list[GraphSample] = []
        for key in requested_keys:
            rows = self._samples_by_channel.get(key, [])
            if not rows:
                continue
            results.extend(self._slice_rows(rows, lower, upper))

        results.sort()
        return results

    def _resolve_requested_keys(self, channel_keys: Sequence[str] | None) -> list[str]:
        if channel_keys:
            requested = [str(key).strip() for key in channel_keys if str(key).strip()]
        elif self._subscriptions:
            requested = sorted(self._subscriptions)
        else:
            requested = self.list_channel_keys()
        return requested

    def _trim_channel(self, channel_key: str) -> None:
        if self._retention_seconds is None:
            return
        rows = self._samples_by_channel.get(channel_key)
        if not rows:
            return
        newest_ts = rows[-1].timestamp
        cutoff = newest_ts - self._retention_seconds
        keep_from = bisect_left([row.timestamp for row in rows], cutoff)
        if keep_from > 0:
            del rows[:keep_from]

    @staticmethod
    def _sample_in_window(sample: GraphSample, start_ts: float | None, end_ts: float | None) -> bool:
        if start_ts is not None and sample.timestamp < start_ts:
            return False
        if end_ts is not None and sample.timestamp > end_ts:
            return False
        return True

    @staticmethod
    def _slice_rows(rows: list[GraphSample], start_ts: float | None, end_ts: float | None) -> list[GraphSample]:
        timestamps = [row.timestamp for row in rows]
        left = 0 if start_ts is None else bisect_left(timestamps, start_ts)
        right = len(rows) if end_ts is None else bisect_right(timestamps, end_ts)
        return rows[left:right]
