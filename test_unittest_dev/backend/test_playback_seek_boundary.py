"""Tests for playback seek boundary semantics and untimestamped event handling.

These test the pure functions from gui.window_host that control which events
are included during tail replay after a snapshot is applied.

Boundary contract:
  - A snapshot represents state *up to and including* its recorded_at.
  - Tail replay starts *strictly after* the snapshot boundary.
  - Tail replay includes events *up to and including* the seek target.
  - bisect path and fallback linear path must produce identical results.

Known limitation (documented, not fixed in this pass):
  If the initial snapshot's recorded_at equals start_wall_time AND the very
  first telemetry event has exactly the same timestamp, the event is excluded
  from tail replay because of the "strictly after" boundary.  In practice this
  requires a sub-millisecond timing collision between start_run() and the first
  packet arrival, which is effectively impossible in the real backend.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone, timedelta

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip


window_host = import_module_or_skip("gui.window_host")

_slice = window_host._slice_playback_tail_events
_dt2key = window_host._datetime_to_seek_key


def _utc(iso: str) -> datetime:
    text = iso.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _make_event(recorded_at: str, **extra) -> dict:
    return {"recorded_at": recorded_at, **extra}


# ---------------------------------------------------------------------------
# Helpers to build parallel event lists + time keys (simulating the seek-index
# that _load_ignitionhistory_playback constructs).
# ---------------------------------------------------------------------------

def _build_seek_index(events, run_start_iso="2026-01-01T00:00:00Z"):
    """Replicate the seek-index build logic from _load_ignitionhistory_playback."""
    run_start_key = _dt2key(_utc(run_start_iso))
    seek_entries = []
    last_known_key = run_start_key
    for original_index, event in enumerate(events):
        event_dt = window_host._extract_event_wall_time(event)
        event_key = _dt2key(event_dt)
        if event_key is not None:
            last_known_key = event_key
        else:
            event_key = last_known_key
        if event_key is None:
            continue
        seek_entries.append((event_key, original_index, event))
    seek_entries.sort(key=lambda entry: (entry[0], entry[1]))
    seek_events = [event for _, _, event in seek_entries]
    time_keys = [key for key, _, _ in seek_entries]
    return seek_events, time_keys


class TestSliceBoundaryBisectPath(unittest.TestCase):
    """Verify boundary semantics when the fast bisect path is used."""

    def _events_and_keys(self):
        events = [
            _make_event("2026-01-01T00:00:00Z", label="at-boundary"),
            _make_event("2026-01-01T00:00:01Z", label="one-sec-after"),
            _make_event("2026-01-01T00:00:02Z", label="two-sec-after"),
            _make_event("2026-01-01T00:00:03Z", label="three-sec-after"),
        ]
        keys = [_dt2key(_utc(e["recorded_at"])) for e in events]
        return events, keys

    def test_events_at_snapshot_boundary_are_excluded(self):
        events, keys = self._events_and_keys()
        result = _slice(
            events,
            replay_start_dt=_utc("2026-01-01T00:00:00Z"),
            seek_dt=_utc("2026-01-01T00:00:03Z"),
            event_time_keys=keys,
        )
        labels = [e["label"] for e in result]
        self.assertNotIn("at-boundary", labels)
        self.assertEqual(labels, ["one-sec-after", "two-sec-after", "three-sec-after"])

    def test_events_at_seek_target_are_included(self):
        events, keys = self._events_and_keys()
        result = _slice(
            events,
            replay_start_dt=_utc("2026-01-01T00:00:00Z"),
            seek_dt=_utc("2026-01-01T00:00:02Z"),
            event_time_keys=keys,
        )
        labels = [e["label"] for e in result]
        self.assertIn("two-sec-after", labels)
        self.assertNotIn("three-sec-after", labels)

    def test_no_events_when_seek_equals_boundary(self):
        """If seek_dt == replay_start_dt, no events should be returned."""
        events, keys = self._events_and_keys()
        result = _slice(
            events,
            replay_start_dt=_utc("2026-01-01T00:00:00Z"),
            seek_dt=_utc("2026-01-01T00:00:00Z"),
            event_time_keys=keys,
        )
        self.assertEqual(result, [])

    def test_multiple_events_at_same_boundary_timestamp_all_excluded(self):
        events = [
            _make_event("2026-01-01T00:00:00Z", label="a-at-boundary"),
            _make_event("2026-01-01T00:00:00Z", label="b-at-boundary"),
            _make_event("2026-01-01T00:00:01Z", label="after"),
        ]
        keys = [_dt2key(_utc(e["recorded_at"])) for e in events]
        result = _slice(
            events,
            replay_start_dt=_utc("2026-01-01T00:00:00Z"),
            seek_dt=_utc("2026-01-01T00:00:01Z"),
            event_time_keys=keys,
        )
        labels = [e["label"] for e in result]
        self.assertNotIn("a-at-boundary", labels)
        self.assertNotIn("b-at-boundary", labels)
        self.assertEqual(labels, ["after"])


class TestSliceBoundaryFallbackPath(unittest.TestCase):
    """Verify fallback linear scan has the same boundary semantics."""

    def test_fallback_excludes_at_boundary(self):
        events = [
            _make_event("2026-01-01T00:00:00Z", label="at-boundary"),
            _make_event("2026-01-01T00:00:01Z", label="after"),
        ]
        # Pass event_time_keys=None to force the fallback linear scan
        result = _slice(
            events,
            replay_start_dt=_utc("2026-01-01T00:00:00Z"),
            seek_dt=_utc("2026-01-01T00:00:01Z"),
            event_time_keys=None,
        )
        labels = [e["label"] for e in result]
        self.assertEqual(labels, ["after"])

    def test_fallback_includes_at_seek_target(self):
        events = [
            _make_event("2026-01-01T00:00:01Z", label="one"),
            _make_event("2026-01-01T00:00:02Z", label="two"),
        ]
        result = _slice(
            events,
            replay_start_dt=_utc("2026-01-01T00:00:00Z"),
            seek_dt=_utc("2026-01-01T00:00:02Z"),
            event_time_keys=None,
        )
        labels = [e["label"] for e in result]
        self.assertIn("two", labels)

    def test_bisect_and_fallback_agree(self):
        """Bisect and fallback must return the same events for the same inputs."""
        events = [
            _make_event("2026-01-01T00:00:00Z", label="at-snap"),
            _make_event("2026-01-01T00:00:01Z", label="a"),
            _make_event("2026-01-01T00:00:02Z", label="b"),
            _make_event("2026-01-01T00:00:03Z", label="c"),
        ]
        keys = [_dt2key(_utc(e["recorded_at"])) for e in events]

        snap_dt = _utc("2026-01-01T00:00:00Z")
        seek_dt = _utc("2026-01-01T00:00:02Z")

        bisect_result = _slice(events, replay_start_dt=snap_dt, seek_dt=seek_dt, event_time_keys=keys)
        fallback_result = _slice(events, replay_start_dt=snap_dt, seek_dt=seek_dt, event_time_keys=None)

        self.assertEqual(
            [e["label"] for e in bisect_result],
            [e["label"] for e in fallback_result],
        )


class TestUntimestampedEventHandling(unittest.TestCase):
    """Events without a parseable wall time must not be silently dropped.

    The seek-index builder assigns untimestamped events the timestamp of
    their nearest preceding timestamped event (or the run start time).
    This keeps them in the bisect path with best-effort temporal placement.
    """

    def test_untimestamped_events_are_preserved_in_seek_index(self):
        events = [
            _make_event("2026-01-01T00:00:01Z", label="timestamped-1"),
            {"label": "no-timestamp"},                                     # no recorded_at at all
            _make_event("2026-01-01T00:00:03Z", label="timestamped-2"),
        ]
        seek_events, time_keys = _build_seek_index(events, "2026-01-01T00:00:00Z")

        # All 3 events should be in the seek index
        self.assertEqual(len(seek_events), 3)
        labels = [e.get("label") for e in seek_events]
        self.assertIn("no-timestamp", labels)

    def test_untimestamped_event_gets_preceding_timestamp(self):
        events = [
            _make_event("2026-01-01T00:00:01Z", label="first"),
            {"label": "untimed"},
            _make_event("2026-01-01T00:00:03Z", label="third"),
        ]
        seek_events, time_keys = _build_seek_index(events, "2026-01-01T00:00:00Z")

        # The untimestamped event should get the same key as "first" (T+1)
        untimed_index = [e.get("label") for e in seek_events].index("untimed")
        first_index = [e.get("label") for e in seek_events].index("first")
        self.assertEqual(time_keys[untimed_index], time_keys[first_index])

    def test_leading_untimestamped_event_gets_run_start_key(self):
        events = [
            {"label": "untimed-first"},
            _make_event("2026-01-01T00:00:02Z", label="timestamped"),
        ]
        seek_events, time_keys = _build_seek_index(events, "2026-01-01T00:00:00Z")

        self.assertEqual(len(seek_events), 2)
        # The leading untimestamped event should get the run start key (T+0)
        untimed_index = [e.get("label") for e in seek_events].index("untimed-first")
        expected_key = _dt2key(_utc("2026-01-01T00:00:00Z"))
        self.assertEqual(time_keys[untimed_index], expected_key)

    def test_untimestamped_events_included_in_tail_slice(self):
        """Untimestamped events should appear in tail replay when their
        approximated timestamp falls in the replay window."""
        events = [
            _make_event("2026-01-01T00:00:01Z", label="first"),
            {"label": "untimed"},
            _make_event("2026-01-01T00:00:03Z", label="third"),
        ]
        seek_events, time_keys = _build_seek_index(events, "2026-01-01T00:00:00Z")

        # Seek from snapshot at T=0 to T=2 — should include "first" and "untimed"
        # (both have key at T+1), but not "third" (at T+3)
        result = _slice(
            seek_events,
            replay_start_dt=_utc("2026-01-01T00:00:00Z"),
            seek_dt=_utc("2026-01-01T00:00:02Z"),
            event_time_keys=time_keys,
        )
        labels = [e.get("label") for e in result]
        self.assertIn("first", labels)
        self.assertIn("untimed", labels)
        self.assertNotIn("third", labels)

    def test_deterministic_across_rebuilds(self):
        """Building the seek index twice from the same events produces
        identical time_keys."""
        events = [
            _make_event("2026-01-01T00:00:01Z", label="a"),
            {"label": "b"},
            {"label": "c"},
            _make_event("2026-01-01T00:00:05Z", label="d"),
        ]
        _, keys_1 = _build_seek_index(events, "2026-01-01T00:00:00Z")
        _, keys_2 = _build_seek_index(events, "2026-01-01T00:00:00Z")
        self.assertEqual(keys_1, keys_2)
