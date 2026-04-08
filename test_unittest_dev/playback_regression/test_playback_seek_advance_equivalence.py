"""Higher-level playback correctness tests: seek vs incremental advance.

Verifies that seek-to-T and incremental advance from 0->T produce
equivalent playback state -- the same events are delivered, no events
are double-applied across snapshot boundaries, and no events are missed
by the incremental path.

These tests exercise the real _handle_playback_seek and
_handle_playback_advance functions from gui.window_host with a
lightweight fake window target (no Qt required).
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip, write_json

window_host = import_module_or_skip("gui.window_host")
psm_mod = import_module_or_skip("gui.playback_state_manager")
catalog_mod = import_module_or_skip("gui.device_catalog")

PlaybackStateManager = psm_mod.PlaybackStateManager
PlaybackRunContext = psm_mod.PlaybackRunContext
BackendDeviceCatalog = catalog_mod.BackendDeviceCatalog

_handle_seek = window_host._handle_playback_seek
_handle_advance = window_host._handle_playback_advance
_dt2key = window_host._datetime_to_seek_key

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _dt(seconds: float) -> datetime:
    return _T0 + timedelta(seconds=seconds)


def _iso(seconds: float) -> str:
    return _dt(seconds).isoformat().replace("+00:00", "Z")


def _ev(t: float, **extra) -> dict[str, Any]:
    """Create an event at *t* seconds after _T0."""
    return {"recorded_at": _iso(t), **extra}


def _build_seek_index(events: list[dict[str, Any]]):
    """Replicate the seek-index build from _load_ignitionhistory_playback."""
    run_start_key = _dt2key(_T0)
    entries: list[tuple[float, int, dict[str, Any]]] = []
    last_key = run_start_key
    for idx, ev in enumerate(events):
        ev_dt = window_host._extract_event_wall_time(ev)
        ev_key = _dt2key(ev_dt)
        if ev_key is not None:
            last_key = ev_key
        else:
            ev_key = last_key
        if ev_key is None:
            continue
        entries.append((ev_key, idx, ev))
    entries.sort(key=lambda e: (e[0], e[1]))
    return [ev for _, _, ev in entries], [k for k, _, _ in entries]


class _FakeTarget:
    """Minimal window-like object that records event delivery.

    Satisfies the interface expected by _handle_playback_seek and
    _handle_playback_advance without any Qt dependency.
    """

    def __init__(self, psm: PlaybackStateManager) -> None:
        self.playback_state = psm
        self.backend_device_catalog = BackendDeviceCatalog()
        self.backend_device_presentation: dict[str, Any] = {}
        self._backend_playback_clock: dict[str, Any] | None = None
        self.controller = None
        self.scada = None
        self.script = None

        # Recorded observations
        self.delivered_events: list[dict[str, Any]] = []
        self.snapshot_applies: list[dict[str, Any]] = []

    def handle_structured_event(self, event: dict[str, Any]) -> None:
        self.delivered_events.append(dict(event))

    def apply_backend_state_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.snapshot_applies.append(dict(snapshot))

    def handle_playback_seek_bootstrap(self, payload: dict[str, Any]) -> None:
        pass

    def handle_playback_loaded(self, payload: dict[str, Any]) -> None:
        pass

    def set_playback_time(self, t: float) -> None:
        pass

    def clear(self) -> None:
        self.delivered_events.clear()
        self.snapshot_applies.clear()


def _make_context(
    events: list[dict[str, Any]],
    *,
    duration: float = 7.0,
    snapshot_index: list[dict[str, Any]] | None = None,
) -> PlaybackRunContext:
    seek_events, time_keys = _build_seek_index(events)
    return PlaybackRunContext(
        run_id="test-run",
        history_dir="/tmp/test",
        playback_source="native",
        metadata={"run_id": "test-run", "start_wall_time": _iso(0)},
        start_dt=_T0,
        end_dt=_dt(duration),
        duration_seconds=duration,
        snapshot_index=snapshot_index or [],
        snapshot_files=[],
        merged_events=list(events),
        seek_events=seek_events,
        event_time_keys=time_keys,
    )


def _event_labels(events: list[dict[str, Any]]) -> list[str]:
    """Extract 'label' field from events for easy comparison."""
    return [e.get("label", "?") for e in events]


# ---------------------------------------------------------------------------
# Standard event fixture: 6 events across 3 streams, all strictly after T=0
# ---------------------------------------------------------------------------

def _standard_events() -> list[dict[str, Any]]:
    return [
        _ev(1, stream="telemetry_in", device_id="PT-001", label="telem-1"),
        _ev(2, stream="telemetry_in", device_id="PT-001", label="telem-2"),
        _ev(3, stream="command_out", device_id="XV-001", label="cmd-3"),
        _ev(4, stream="telemetry_in", device_id="PT-001", label="telem-4"),
        _ev(5, stream="operator_action", action="hold", label="op-5"),
        _ev(6, stream="telemetry_in", device_id="PT-001", label="telem-6"),
    ]


# ===================================================================
# Test: Seek vs single-step advance deliver the same events
# ===================================================================

class TestSeekAdvanceEventEquivalence(unittest.TestCase):
    """Core equivalence: seek(T) and advance(0->T) produce the same events."""

    def _seek_to(self, target: _FakeTarget, t: float) -> list[dict]:
        target.clear()
        target.playback_state.position_seconds = 0.0
        target.playback_state.last_event_index = 0
        _handle_seek(target, t)
        return list(target.delivered_events)

    def _advance_to(self, target: _FakeTarget, t: float, *, step: float = 1.0) -> list[dict]:
        """Advance from 0 to t in steps, collecting all delivered events."""
        target.clear()
        target.playback_state.position_seconds = 0.0
        target.playback_state.last_event_index = 0
        cursor = 0.0
        while cursor < t:
            prev = cursor
            cursor = min(cursor + step, t)
            _handle_advance(target, prev, cursor)
        return list(target.delivered_events)

    def test_single_seek_delivers_all_events_up_to_target(self):
        events = _standard_events()
        ctx = _make_context(events, duration=7.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        delivered = self._seek_to(target, 6.0)
        labels = _event_labels(delivered)
        self.assertEqual(labels, ["telem-1", "telem-2", "cmd-3", "telem-4", "op-5", "telem-6"])

    def test_seek_and_full_advance_deliver_same_events(self):
        """No intermediate snapshots: seek(6) and advance(0->6) must
        deliver the exact same events in the same order."""
        events = _standard_events()
        ctx = _make_context(events, duration=7.0)

        # Seek path
        psm_seek = PlaybackStateManager()
        psm_seek.load_context(ctx)
        target_seek = _FakeTarget(psm_seek)
        seek_events = self._seek_to(target_seek, 6.0)

        # Advance path (step=1.0 so each step <= 2s)
        psm_adv = PlaybackStateManager()
        psm_adv.load_context(ctx)
        target_adv = _FakeTarget(psm_adv)
        adv_events = self._advance_to(target_adv, 6.0, step=1.0)

        self.assertEqual(
            _event_labels(seek_events),
            _event_labels(adv_events),
            "Seek and advance must deliver the same events",
        )

    def test_stepwise_advance_matches_single_seek(self):
        """Advancing in 0.5s steps delivers the same cumulative events
        as a single seek to the same time."""
        events = _standard_events()
        ctx = _make_context(events, duration=7.0)

        psm_seek = PlaybackStateManager()
        psm_seek.load_context(ctx)
        seek_labels = _event_labels(self._seek_to(_FakeTarget(psm_seek), 5.0))

        psm_adv = PlaybackStateManager()
        psm_adv.load_context(ctx)
        adv_labels = _event_labels(self._advance_to(_FakeTarget(psm_adv), 5.0, step=0.5))

        self.assertEqual(seek_labels, adv_labels)

    def test_both_paths_agree_on_final_event_index(self):
        events = _standard_events()
        ctx = _make_context(events, duration=7.0)

        psm_seek = PlaybackStateManager()
        psm_seek.load_context(ctx)
        target_seek = _FakeTarget(psm_seek)
        self._seek_to(target_seek, 4.5)

        psm_adv = PlaybackStateManager()
        psm_adv.load_context(ctx)
        target_adv = _FakeTarget(psm_adv)
        self._advance_to(target_adv, 4.5, step=0.5)

        self.assertEqual(
            psm_seek.last_event_index,
            psm_adv.last_event_index,
            "Both paths must agree on last_event_index after reaching the same time",
        )

    def test_seek_to_end_delivers_all_events(self):
        events = _standard_events()
        ctx = _make_context(events, duration=7.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        delivered = self._seek_to(target, 7.0)
        self.assertEqual(len(delivered), 6)


# ===================================================================
# Test: Snapshot boundaries do not cause double-apply or gaps
# ===================================================================

class TestSnapshotBoundaryCorrectness(unittest.TestCase):
    """Seek with a snapshot at T=3 should replay only events strictly
    after T=3.  Events at or before the boundary are captured by the
    snapshot and must NOT be re-delivered as tail events."""

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.snapshot_dir = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_snapshot(self, relative_seconds: float, index: int) -> dict[str, Any]:
        """Write a synthetic snapshot file and return a snapshot_index entry."""
        snapshot_path = self.snapshot_dir / f"{index:06d}.json"
        payload = {
            "recorded_at": _iso(relative_seconds),
            "snapshot_index": index,
            "state": {
                "device_registry": {"devices": []},
                "device_runtime": {"by_id": {}},
                "playback_clock": {"position_seconds": relative_seconds},
            },
        }
        write_json(snapshot_path, payload)
        return {
            "path": str(snapshot_path),
            "snapshot_index": index,
            "recorded_at": _iso(relative_seconds),
            "relative_seconds": relative_seconds,
            "has_state": True,
        }

    def test_seek_with_snapshot_replays_only_post_boundary_events(self):
        events = _standard_events()  # T=1..6
        snap_entry = self._write_snapshot(3.0, index=1)
        ctx = _make_context(events, duration=7.0, snapshot_index=[snap_entry])

        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        _handle_seek(target, 6.0)

        tail_labels = _event_labels(target.delivered_events)
        # Events at T=1,2,3 are captured by the snapshot at T=3.
        # Only T=4,5,6 should appear as tail replay events.
        self.assertEqual(tail_labels, ["telem-4", "op-5", "telem-6"])

    def test_event_at_exact_snapshot_boundary_not_in_tail(self):
        """An event at exactly T=3 and a snapshot at T=3: the event must
        NOT be delivered as a tail event (the snapshot already includes it)."""
        events = _standard_events()  # cmd-3 is at T=3
        snap_entry = self._write_snapshot(3.0, index=1)
        ctx = _make_context(events, duration=7.0, snapshot_index=[snap_entry])

        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        _handle_seek(target, 5.0)

        tail_labels = _event_labels(target.delivered_events)
        self.assertNotIn("cmd-3", tail_labels,
                         "Event at exact snapshot boundary must not be re-delivered")
        self.assertIn("telem-4", tail_labels)
        self.assertIn("op-5", tail_labels)

    def test_seek_without_snapshot_replays_all_from_start(self):
        """With no snapshots at all, seek replays every event from start."""
        events = _standard_events()
        ctx = _make_context(events, duration=7.0, snapshot_index=[])

        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        _handle_seek(target, 6.0)
        self.assertEqual(len(target.delivered_events), 6)

    def test_snapshot_apply_is_called_during_seek(self):
        """Seek with a snapshot entry must apply the snapshot state."""
        events = _standard_events()
        snap_entry = self._write_snapshot(3.0, index=1)
        ctx = _make_context(events, duration=7.0, snapshot_index=[snap_entry])

        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        _handle_seek(target, 5.0)

        self.assertTrue(len(target.snapshot_applies) > 0,
                        "Snapshot should be applied during seek")


# ===================================================================
# Test: Incremental advance completeness and ordering
# ===================================================================

class TestIncrementalAdvanceCompleteness(unittest.TestCase):
    """Advance in small steps must not miss events."""

    def test_advance_covers_every_event_between_ticks(self):
        """Events that fall between two advance tick boundaries
        must still be delivered."""
        # Events at T=0.3, T=0.7, T=1.3 — none align with 0.5s ticks
        events = [
            _ev(0.3, label="a"),
            _ev(0.7, label="b"),
            _ev(1.3, label="c"),
        ]
        ctx = _make_context(events, duration=2.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        # Advance in 0.5s steps: 0->0.5, 0.5->1.0, 1.0->1.5
        _handle_advance(target, 0.0, 0.5)   # should pick up T=0.3
        _handle_advance(target, 0.5, 1.0)   # should pick up T=0.7
        _handle_advance(target, 1.0, 1.5)   # should pick up T=1.3

        labels = _event_labels(target.delivered_events)
        self.assertEqual(labels, ["a", "b", "c"])

    def test_advance_does_not_double_deliver_on_boundary(self):
        """An event at exactly T=1.0 is delivered in one tick, not two,
        when ticks land on [0.5, 1.0] then [1.0, 1.5]."""
        events = [
            _ev(0.5, label="half"),
            _ev(1.0, label="one"),
            _ev(1.5, label="onehalf"),
        ]
        ctx = _make_context(events, duration=2.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        _handle_advance(target, 0.0, 1.0)   # T=0.5 and T=1.0
        _handle_advance(target, 1.0, 2.0)   # T=1.5 only — T=1.0 already delivered

        labels = _event_labels(target.delivered_events)
        self.assertEqual(labels.count("one"), 1,
                         "Event at tick boundary must be delivered exactly once")
        self.assertEqual(labels, ["half", "one", "onehalf"])

    def test_advance_large_gap_falls_back_to_seek(self):
        """A gap > 2s triggers fallback to full seek."""
        events = [_ev(1, label="a"), _ev(4, label="b")]
        ctx = _make_context(events, duration=5.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        # Single 4s advance — exceeds the 2s threshold
        _handle_advance(target, 0.0, 4.0)

        labels = _event_labels(target.delivered_events)
        # Should still deliver both events (via seek fallback)
        self.assertIn("a", labels)
        self.assertIn("b", labels)


# ===================================================================
# Test: Advance after seek continues from the correct index
# ===================================================================

class TestSeekThenAdvanceContinuity(unittest.TestCase):
    """After seeking to T, a subsequent advance from T should continue
    delivering events without gaps or repeats."""

    def test_advance_after_seek_continues_correctly(self):
        events = _standard_events()  # T=1..6
        ctx = _make_context(events, duration=7.0)

        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        # Seek to T=3 (delivers T=1, T=2, T=3)
        _handle_seek(target, 3.0)
        seek_labels = _event_labels(target.delivered_events)
        self.assertEqual(seek_labels, ["telem-1", "telem-2", "cmd-3"])

        # Advance from T=3 to T=5 (should deliver T=4, T=5 only)
        target.clear()
        _handle_advance(target, 3.0, 5.0)
        adv_labels = _event_labels(target.delivered_events)
        self.assertEqual(adv_labels, ["telem-4", "op-5"])

    def test_seek_forward_then_seek_backward_resets(self):
        """Seeking backward re-delivers earlier events (full reset)."""
        events = _standard_events()
        ctx = _make_context(events, duration=7.0)

        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        # Seek forward to T=5
        _handle_seek(target, 5.0)
        self.assertEqual(len(target.delivered_events), 5)

        # Seek backward to T=2
        target.clear()
        _handle_seek(target, 2.0)
        labels = _event_labels(target.delivered_events)
        self.assertEqual(labels, ["telem-1", "telem-2"])

    def test_full_round_trip_seek_advance_seek(self):
        """Seek to T=2, advance to T=4, seek to T=6: cumulative delivered
        event set equals all events up to T=6."""
        events = _standard_events()
        ctx = _make_context(events, duration=7.0)

        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        all_delivered: list[dict] = []

        _handle_seek(target, 2.0)
        all_delivered.extend(target.delivered_events)

        target.clear()
        _handle_advance(target, 2.0, 4.0)
        all_delivered.extend(target.delivered_events)

        target.clear()
        _handle_seek(target, 6.0)
        # Seek resets from nearest snapshot; with no snapshots this replays from start
        # The important thing: after this seek, we should have events up to T=6

        final_labels = _event_labels(target.delivered_events)
        self.assertEqual(final_labels,
                         ["telem-1", "telem-2", "cmd-3", "telem-4", "op-5", "telem-6"])


# ===================================================================
# Test: Mixed-stream handling
# ===================================================================

class TestMixedStreamEquivalence(unittest.TestCase):
    """Both seek and advance must deliver all event streams."""

    def test_all_stream_types_present_after_seek(self):
        events = _standard_events()
        ctx = _make_context(events, duration=7.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        _handle_seek(target, 6.0)

        streams = {e.get("stream") for e in target.delivered_events}
        self.assertIn("telemetry_in", streams)
        self.assertIn("command_out", streams)
        self.assertIn("operator_action", streams)

    def test_all_stream_types_present_after_advance(self):
        events = _standard_events()
        ctx = _make_context(events, duration=7.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        cursor = 0.0
        while cursor < 6.0:
            prev = cursor
            cursor = min(cursor + 1.0, 6.0)
            _handle_advance(target, prev, cursor)

        streams = {e.get("stream") for e in target.delivered_events}
        self.assertIn("telemetry_in", streams)
        self.assertIn("command_out", streams)
        self.assertIn("operator_action", streams)

    def test_stream_ordering_preserved(self):
        """Events must be delivered in temporal order regardless of stream."""
        events = _standard_events()  # interleaved streams at T=1..6
        ctx = _make_context(events, duration=7.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        _handle_seek(target, 6.0)

        timestamps = []
        for ev in target.delivered_events:
            ts_str = ev.get("recorded_at", "")
            if ts_str:
                timestamps.append(ts_str)
        self.assertEqual(timestamps, sorted(timestamps),
                         "Events must be delivered in chronological order")
