# gui/graph_provider.py

"""Shared graph data provider interfaces and in-memory storage.

This module defines the common provider contract used by graph widgets and
mode-specific adapters, plus a small in-memory implementation that stores
``GraphSample`` records by channel and supports subscription and time-window
filtering.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from bisect import bisect_left, bisect_right
from collections import defaultdict
from typing import Callable, Iterable, Sequence

from .graph_data import GraphChannelDescriptor, GraphSample, GraphWindow

GraphSamplesListener = Callable[[list[GraphSample]], None]


class BaseGraphDataProvider(ABC):
    """Define the shared interface for graph data sources.

    The provider API is intentionally UI-agnostic so graph widgets can consume
    the same ``GraphSample`` records from live and playback sources.
    """

    def __init__(self) -> None:
        """Initialize provider lifecycle state, subscriptions, and listeners."""
        self._running = False
        self._subscriptions: set[str] = set()
        self._window = GraphWindow()
        self._listeners: list[GraphSamplesListener] = []

    @property
    def running(self) -> bool:
        """Return whether the provider has been started."""
        return self._running

    @property
    def subscriptions(self) -> tuple[str, ...]:
        """Return the current subscribed channel keys in sorted order."""
        return tuple(sorted(self._subscriptions))

    @property
    def window(self) -> GraphWindow:
        """Return the active graph time window filter."""
        return self._window

    def start(self) -> None:
        """Mark the provider as running and invoke the start hook once."""
        if self._running:
            return
        self._running = True
        self._on_start()

    def stop(self) -> None:
        """Mark the provider as stopped and invoke the stop hook once."""
        if not self._running:
            return
        self._running = False
        self._on_stop()

    def subscribe(self, channel_keys: Sequence[str]) -> None:
        """Add channel subscriptions and notify the subscription hook.

        Args:
            channel_keys: Channel keys to subscribe to. Empty and whitespace-only
                keys are ignored.
        """
        normalized = {str(key).strip() for key in channel_keys if str(key).strip()}
        if not normalized:
            return
        self._subscriptions.update(normalized)
        self._on_subscription_changed()

    def unsubscribe(self, channel_keys: Sequence[str]) -> None:
        """Remove channel subscriptions and notify the subscription hook.

        Args:
            channel_keys: Channel keys to remove. Missing keys are ignored.
        """
        removed = False
        for key in channel_keys:
            text = str(key).strip()
            if text in self._subscriptions:
                self._subscriptions.remove(text)
                removed = True
        if removed:
            self._on_subscription_changed()

    def clear_subscriptions(self) -> None:
        """Remove all channel subscriptions and notify the subscription hook."""
        if not self._subscriptions:
            return
        self._subscriptions.clear()
        self._on_subscription_changed()

    def set_time_window(
        self, *, start_ts: float | None = None, end_ts: float | None = None
    ) -> None:
        """Replace the active graph time window and notify the window hook.

        Args:
            start_ts: Inclusive lower timestamp bound, or None for no lower
                bound.
            end_ts: Inclusive upper timestamp bound, or None for no upper bound.
        """
        self._window = GraphWindow(start_ts=start_ts, end_ts=end_ts)
        self._on_window_changed()

    def add_listener(self, callback: GraphSamplesListener) -> None:
        """Register a listener for emitted sample batches.

        Args:
            callback: Listener that receives appended sample batches.
        """
        if callback in self._listeners:
            return
        self._listeners.append(callback)

    def remove_listener(self, callback: GraphSamplesListener) -> None:
        """Unregister a previously added sample listener.

        Args:
            callback: Listener to remove.
        """
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _emit_samples(self, samples: Iterable[GraphSample]) -> None:
        """Send a non-empty sample batch to all registered listeners.

        Args:
            samples: Sample records to emit to listeners.
        """
        payload = list(samples)
        if not payload:
            return
        for callback in list(self._listeners):
            callback(payload)

    def _on_start(self) -> None:
        """Handle provider-specific startup work."""
        pass

    def _on_stop(self) -> None:
        """Handle provider-specific shutdown work."""
        pass

    def _on_subscription_changed(self) -> None:
        """React to subscription changes."""
        pass

    def _on_window_changed(self) -> None:
        """React to time-window changes."""
        pass

    @abstractmethod
    def get_channel_descriptors(self) -> list[GraphChannelDescriptor]:
        """Return metadata for channels available from this provider.

        Returns:
            A list of channel descriptors that describe the provider's known
            graph channels.
        """
        raise NotImplementedError

    @abstractmethod
    def get_samples(
        self,
        *,
        channel_keys: Sequence[str] | None = None,
        start_ts: float | None = None,
        end_ts: float | None = None,
    ) -> list[GraphSample]:
        """Return samples filtered by channel and time range.

        Args:
            channel_keys: Optional channel keys to fetch. When omitted,
                implementations may use current subscriptions or all known
                channels.
            start_ts: Inclusive lower timestamp bound, or None for no lower
                bound.
            end_ts: Inclusive upper timestamp bound, or None for no upper bound.

        Returns:
            Sample records matching the requested channels and time range.
        """
        raise NotImplementedError


class InMemoryGraphDataProvider(BaseGraphDataProvider):
    """Store graph samples in memory for tests and simple adapters.

    Samples are indexed by channel key, kept in timestamp order, optionally
    trimmed by a retention window, and emitted to listeners when newly ingested
    samples match the active subscription and time-window filters.
    """

    def __init__(self, *, retention_seconds: float | None = None) -> None:
        """Initialize empty channel storage and optional retention trimming.

        Args:
            retention_seconds: Maximum age of retained samples per channel based
                on the newest ingested sample timestamp, or None to keep all
                samples.
        """
        super().__init__()
        self._retention_seconds = (
            None if retention_seconds is None else float(retention_seconds)
        )
        self._samples_by_channel: dict[str, list[GraphSample]] = defaultdict(list)
        self._descriptors: dict[str, GraphChannelDescriptor] = {}

    def register_channel(self, descriptor: GraphChannelDescriptor) -> None:
        """Register or replace metadata for a graph channel.

        Args:
            descriptor: Channel descriptor keyed by ``descriptor.channel_key``.
        """
        self._descriptors[descriptor.channel_key] = descriptor

    def register_channels(self, descriptors: Iterable[GraphChannelDescriptor]) -> None:
        """Register multiple channel descriptors.

        Args:
            descriptors: Channel descriptors to register.
        """
        for descriptor in descriptors:
            self.register_channel(descriptor)

    def get_channel_descriptors(self) -> list[GraphChannelDescriptor]:
        """Return all registered channel descriptors sorted by channel key.

        Returns:
            Sorted channel descriptors known to the provider.
        """
        descriptors = list(self._descriptors.values())
        descriptors.sort(key=lambda item: item.channel_key)
        return descriptors

    def ingest_samples(self, samples: Iterable[GraphSample]) -> list[GraphSample]:
        """Insert samples, update descriptors, and emit visible appended rows.

        Each sample is inserted into its channel's timestamp-ordered list. When
        a channel descriptor is missing, one is synthesized from the sample.
        After optional retention trimming, appended samples that match the
        current subscription set and active time window are emitted to listeners.

        Args:
            samples: Sample records to ingest.

        Returns:
            The subset of ingested samples that was emitted to listeners.
        """
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
                if self._sample_in_window(
                    sample, self._window.start_ts, self._window.end_ts
                ):
                    appended.append(sample)

        self._emit_samples(appended)
        return appended

    def clear(self) -> None:
        """Remove all stored samples and registered descriptors."""
        self._samples_by_channel.clear()
        self._descriptors.clear()

    def list_channel_keys(self) -> list[str]:
        """Return all known channel keys from samples and descriptors.

        Returns:
            Sorted channel keys known to the provider.
        """
        keys = set(self._samples_by_channel.keys()) | set(self._descriptors.keys())
        return sorted(keys)

    def get_samples(
        self,
        *,
        channel_keys: Sequence[str] | None = None,
        start_ts: float | None = None,
        end_ts: float | None = None,
    ) -> list[GraphSample]:
        """Return stored samples filtered by channel and time range.

        When ``channel_keys`` is omitted, the provider uses the current
        subscriptions if any exist; otherwise it returns samples from all known
        channels. The requested time bounds override the provider window when
        supplied.

        Args:
            channel_keys: Optional channel keys to fetch.
            start_ts: Inclusive lower timestamp bound, or None to use the active
                window lower bound.
            end_ts: Inclusive upper timestamp bound, or None to use the active
                window upper bound.

        Returns:
            Matching samples from the selected channels, sorted across channels.
        """
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
        """Resolve the channel keys used for a sample query.

        Args:
            channel_keys: Explicit channel keys requested by the caller.

        Returns:
            The explicit request when present, otherwise the current
            subscriptions, or all known channel keys when there are no
            subscriptions.
        """
        if channel_keys:
            requested = [str(key).strip() for key in channel_keys if str(key).strip()]
        elif self._subscriptions:
            requested = sorted(self._subscriptions)
        else:
            requested = self.list_channel_keys()
        return requested

    def _trim_channel(self, channel_key: str) -> None:
        """Drop expired samples from one channel based on retention settings.

        Args:
            channel_key: Channel whose stored samples should be trimmed.
        """
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
    def _sample_in_window(
        sample: GraphSample, start_ts: float | None, end_ts: float | None
    ) -> bool:
        """Return whether a sample falls within an inclusive time window.

        Args:
            sample: Sample to test.
            start_ts: Inclusive lower timestamp bound, or None for no lower
                bound.
            end_ts: Inclusive upper timestamp bound, or None for no upper bound.

        Returns:
            True when the sample timestamp falls within the requested bounds.
        """
        if start_ts is not None and sample.timestamp < start_ts:
            return False
        if end_ts is not None and sample.timestamp > end_ts:
            return False
        return True

    @staticmethod
    def _slice_rows(
        rows: list[GraphSample], start_ts: float | None, end_ts: float | None
    ) -> list[GraphSample]:
        """Return the timestamp slice for one channel's stored rows.

        Args:
            rows: Timestamp-sorted sample rows from a single channel.
            start_ts: Inclusive lower timestamp bound, or None for no lower
                bound.
            end_ts: Inclusive upper timestamp bound, or None for no upper bound.

        Returns:
            The contiguous subset of rows whose timestamps fall within the
            requested bounds.
        """
        timestamps = [row.timestamp for row in rows]
        left = 0 if start_ts is None else bisect_left(timestamps, start_ts)
        right = len(rows) if end_ts is None else bisect_right(timestamps, end_ts)
        return rows[left:right]
