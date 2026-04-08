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

import unittest
from copy import deepcopy
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
        # Forward to controller child, mirroring WindowHostFacade behavior
        if self.controller is not None:
            handler = getattr(self.controller, "handle_structured_event", None)
            if callable(handler):
                handler(dict(event))

    def apply_backend_state_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.snapshot_applies.append(dict(snapshot))
        # Forward to controller child, mirroring _apply_playback_state_snapshot
        if self.controller is not None:
            handler = getattr(self.controller, "apply_backend_state_snapshot", None)
            if callable(handler):
                handler(dict(snapshot))

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


# ===================================================================
# Test: Reconstructed playback state is populated after seek/advance
# ===================================================================

_build_rs = window_host._build_reconstructed_playback_state
_resolve_applied = window_host._resolve_applied_snapshot_state


class _FakeController:
    """Simulates a controller window with _last_backend_snapshot and clock containers.

    Also implements the playback event state tracking from
    ControllerWindow._apply_playback_event_state so that tail events
    update the same state containers during test replay.
    """
    playback_mode = True

    _PLAYBACK_RUN_START_TYPES = frozenset({"run_started", "run_archive_initialized"})
    _PLAYBACK_RUN_FINISH_TYPES = frozenset({"run_finish_requested", "run_archive_finalizing"})
    _PLAYBACK_SCRIPT_START_TYPES = frozenset({"script_started"})
    _PLAYBACK_SCRIPT_STOP_TYPES = frozenset({"script_stopped", "script_finished"})
    _PLAYBACK_SCRIPT_HOLD_TYPES = frozenset({"script_held"})
    _PLAYBACK_SCRIPT_CONTINUE_TYPES = frozenset({"script_continued"})

    def __init__(self, snapshot_state: dict[str, Any] | None = None) -> None:
        self._last_backend_snapshot = deepcopy(snapshot_state) if snapshot_state else None
        self._backend_mission_clock = None
        self._backend_recording_clock = None

        if isinstance(snapshot_state, dict):
            mc = snapshot_state.get("mission_clock")
            if isinstance(mc, dict):
                self._backend_mission_clock = dict(mc)
            rc = snapshot_state.get("recording_clock")
            if isinstance(rc, dict):
                self._backend_recording_clock = dict(rc)

    def apply_backend_state_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._last_backend_snapshot = deepcopy(snapshot)
        mc = snapshot.get("mission_clock")
        if isinstance(mc, dict):
            self._backend_mission_clock = dict(mc)
        rc = snapshot.get("recording_clock")
        if isinstance(rc, dict):
            self._backend_recording_clock = dict(rc)

    def handle_structured_event(self, event: dict[str, Any]) -> None:
        self._apply_playback_event_state(event)

    def _apply_playback_event_state(self, payload: dict) -> None:
        stream = str(payload.get("stream") or payload.get("event_kind") or "")
        if stream != "system_event":
            return
        event_type = str(payload.get("event_type") or "").strip().lower()
        if not event_type:
            return
        snapshot = self._last_backend_snapshot
        if not isinstance(snapshot, dict):
            return
        if event_type in self._PLAYBACK_RUN_START_TYPES:
            run = snapshot.get("run")
            if isinstance(run, dict):
                run["is_running"] = True
                run["status"] = "running"
        elif event_type in self._PLAYBACK_RUN_FINISH_TYPES:
            run = snapshot.get("run")
            if isinstance(run, dict):
                run["is_running"] = False
                run["status"] = "completed"
        elif event_type in self._PLAYBACK_SCRIPT_START_TYPES:
            sr = snapshot.get("script_runner")
            if isinstance(sr, dict):
                sr["is_running"] = True
                sr["is_held"] = False
                name = payload.get("name")
                if isinstance(name, str) and name.strip():
                    sr["name"] = name.strip()
        elif event_type in self._PLAYBACK_SCRIPT_STOP_TYPES:
            sr = snapshot.get("script_runner")
            if isinstance(sr, dict):
                sr["is_running"] = False
                sr["is_held"] = False
        elif event_type in self._PLAYBACK_SCRIPT_HOLD_TYPES:
            sr = snapshot.get("script_runner")
            if isinstance(sr, dict):
                sr["is_held"] = True
        elif event_type in self._PLAYBACK_SCRIPT_CONTINUE_TYPES:
            sr = snapshot.get("script_runner")
            if isinstance(sr, dict):
                sr["is_held"] = False
        elif event_type == "backend_health_changed":
            health = snapshot.get("health")
            if isinstance(health, dict):
                overall = payload.get("overall_status")
                if isinstance(overall, str):
                    health["overall_status"] = overall.strip()
                warnings = payload.get("active_warnings")
                if isinstance(warnings, list):
                    health["active_warnings"] = list(warnings)
                    health["active_warning_count"] = len(warnings)


class TestResolveAppliedSnapshotState(unittest.TestCase):
    """Verify _resolve_applied_snapshot_state prefers controller's container."""

    def test_prefers_controller_last_backend_snapshot(self):
        ctrl_state = {
            "run": {"status": "running", "mode": "live"},
            "script_runner": {"is_running": True, "name": "fire-test"},
            "alarms": {"active_alarm_count": 2},
        }
        target = _FakeTarget(PlaybackStateManager())
        target.controller = _FakeController(ctrl_state)

        result = _resolve_applied(target)

        self.assertEqual(result["run"]["status"], "running")
        self.assertEqual(result["script_runner"]["name"], "fire-test")
        self.assertEqual(result["alarms"]["active_alarm_count"], 2)

    def test_falls_back_to_playback_active_snapshot_when_no_controller(self):
        target = _FakeTarget(PlaybackStateManager())
        target.controller = None
        target.playback_active_snapshot = {
            "state": {
                "run": {"status": "completed"},
            }
        }

        result = _resolve_applied(target)
        self.assertEqual(result["run"]["status"], "completed")

    def test_unwraps_state_key_in_fallback(self):
        target = _FakeTarget(PlaybackStateManager())
        target.controller = None
        # Snapshot with state wrapper
        target.playback_active_snapshot = {
            "state": {"run": {"status": "from_wrapper"}},
            "recorded_at": "2026-01-01T00:00:00Z",
        }

        result = _resolve_applied(target)
        self.assertEqual(result["run"]["status"], "from_wrapper")

    def test_fallback_without_state_key_uses_payload_directly(self):
        target = _FakeTarget(PlaybackStateManager())
        target.controller = None
        # Snapshot without state wrapper (old-format snapshots)
        target.playback_active_snapshot = {
            "run": {"status": "direct_payload"},
            "mission_clock": {"seconds": 42.0},
        }

        result = _resolve_applied(target)
        self.assertEqual(result["run"]["status"], "direct_payload")


class TestReconstructedStateReadsControllerContainers(unittest.TestCase):
    """Verify _build_reconstructed_playback_state reads from controller
    post-apply containers, not just the raw snapshot payload."""

    def test_reads_run_status_from_controller_snapshot(self):
        psm = PlaybackStateManager()
        psm.load_context(_make_context(_standard_events(), duration=7.0))
        target = _FakeTarget(psm)
        target.controller = _FakeController({
            "run": {"status": "running", "mode": "live", "test_name": "valve-test", "operator": "Eric"},
        })

        rs = _build_rs(target, 3.0)

        self.assertEqual(rs["run_status"], "running")
        self.assertEqual(rs["run_mode"], "live")
        self.assertEqual(rs["test_name"], "valve-test")
        self.assertEqual(rs["operator"], "Eric")

    def test_reads_script_from_controller_snapshot(self):
        psm = PlaybackStateManager()
        psm.load_context(_make_context(_standard_events(), duration=7.0))
        target = _FakeTarget(psm)
        target.controller = _FakeController({
            "script_runner": {
                "is_running": True,
                "name": "static_fire",
                "current_step_name": "ignite",
                "is_held": False,
            },
        })

        rs = _build_rs(target, 3.0)

        self.assertTrue(rs["script_running"])
        self.assertEqual(rs["script_name"], "static_fire")
        self.assertEqual(rs["script_step_name"], "ignite")
        self.assertFalse(rs["script_is_held"])

    def test_reads_alarms_from_controller_snapshot(self):
        psm = PlaybackStateManager()
        psm.load_context(_make_context(_standard_events(), duration=7.0))
        target = _FakeTarget(psm)
        target.controller = _FakeController({
            "alarms": {"active_alarm_count": 3, "active_fault_count": 1},
        })

        rs = _build_rs(target, 3.0)

        self.assertEqual(rs["active_alarm_count"], 3)
        self.assertEqual(rs["active_fault_count"], 1)

    def test_reads_mission_clock_from_controller_container(self):
        """Controller's _backend_mission_clock is preferred over the
        snapshot dict's mission_clock section."""
        psm = PlaybackStateManager()
        psm.load_context(_make_context(_standard_events(), duration=7.0))
        target = _FakeTarget(psm)
        target.controller = _FakeController({
            "mission_clock": {"seconds": 45.5, "state": "running"},
        })

        rs = _build_rs(target, 3.0)

        self.assertAlmostEqual(rs["mission_clock_seconds"], 45.5)
        self.assertEqual(rs["mission_clock_state"], "running")

    def test_reads_recording_clock_from_controller_container(self):
        psm = PlaybackStateManager()
        psm.load_context(_make_context(_standard_events(), duration=7.0))
        target = _FakeTarget(psm)
        target.controller = _FakeController({
            "recording_clock": {"active": True, "elapsed_seconds": 120.0},
        })

        rs = _build_rs(target, 3.0)

        self.assertTrue(rs["recording_active"])
        self.assertAlmostEqual(rs["recording_elapsed_seconds"], 120.0)

    def test_no_controller_falls_back_to_snapshot_payload(self):
        """When controller is None, builder falls back to facade's
        playback_active_snapshot with state-key unwrapping."""
        psm = PlaybackStateManager()
        psm.load_context(_make_context(_standard_events(), duration=7.0))
        target = _FakeTarget(psm)
        target.controller = None
        target.playback_active_snapshot = {
            "state": {
                "run": {"status": "completed", "test_name": "fallback-test"},
                "script_runner": {"is_running": False},
                "alarms": {"active_alarm_count": 0, "active_fault_count": 0},
            },
        }

        rs = _build_rs(target, 3.0)

        self.assertEqual(rs["run_status"], "completed")
        self.assertEqual(rs["test_name"], "fallback-test")
        self.assertFalse(rs["script_running"])


class TestReconstructedStateAfterSeek(unittest.TestCase):
    """After seek, psm.reconstructed_state must be a non-None dict
    with position and reconstruction metadata."""

    def test_seek_populates_reconstructed_state(self):
        events = _standard_events()
        ctx = _make_context(events, duration=7.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        self.assertIsNone(psm.reconstructed_state)
        _handle_seek(target, 5.0)

        rs = psm.reconstructed_state
        self.assertIsNotNone(rs)
        self.assertAlmostEqual(rs["position_seconds"], 5.0)
        self.assertEqual(rs["duration_seconds"], 7.0)
        self.assertEqual(rs["run_id"], "test-run")

    def test_advance_populates_reconstructed_state(self):
        events = _standard_events()
        ctx = _make_context(events, duration=7.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        _handle_seek(target, 1.0)
        _handle_advance(target, 1.0, 3.0)

        rs = psm.reconstructed_state
        self.assertIsNotNone(rs)
        self.assertAlmostEqual(rs["position_seconds"], 3.0)

    def test_seek_records_tail_event_count(self):
        events = _standard_events()
        ctx = _make_context(events, duration=7.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        _handle_seek(target, 6.0)

        rs = psm.reconstructed_state
        self.assertEqual(rs["tail_event_count"], 6)

    def test_advance_records_incremental_event_count(self):
        events = _standard_events()
        ctx = _make_context(events, duration=7.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        _handle_seek(target, 2.0)
        _handle_advance(target, 2.0, 4.0)

        rs = psm.reconstructed_state
        # T=3 and T=4 are the new events delivered in the advance step
        self.assertEqual(rs["tail_event_count"], 2)

    def test_reconstructed_state_has_expected_fields(self):
        events = _standard_events()
        ctx = _make_context(events, duration=7.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        _handle_seek(target, 3.0)

        rs = psm.reconstructed_state
        expected_keys = {
            "position_seconds", "duration_seconds", "wall_time_iso", "run_id",
            "tail_event_count", "restored_from_snapshot",
            "run_status", "run_mode", "run_is_running", "test_name", "operator",
            "script_running", "script_name", "script_step_name", "script_is_held",
            "overall_health_status", "active_warning_count",
            "active_alarm_count", "active_fault_count",
            "mission_clock_seconds", "mission_clock_state",
            "recording_active", "recording_elapsed_seconds",
            "device_count",
        }
        self.assertTrue(expected_keys.issubset(set(rs.keys())),
                        f"Missing keys: {expected_keys - set(rs.keys())}")

    def test_seek_backward_updates_reconstructed_state(self):
        events = _standard_events()
        ctx = _make_context(events, duration=7.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _FakeTarget(psm)

        _handle_seek(target, 6.0)
        self.assertAlmostEqual(psm.reconstructed_state["position_seconds"], 6.0)

        _handle_seek(target, 2.0)
        self.assertAlmostEqual(psm.reconstructed_state["position_seconds"], 2.0)


# ===================================================================
# Test: Tail replay updates controller state for reconstructed state
# ===================================================================

def _make_target_with_controller(
    psm: PlaybackStateManager,
    snapshot_state: dict[str, Any],
) -> _FakeTarget:
    """Build a _FakeTarget with a _FakeController wired as the controller child.

    The facade dispatches apply_backend_state_snapshot and
    handle_structured_event to the controller, so tail events during
    seek/advance will update the controller's _last_backend_snapshot.
    """
    target = _FakeTarget(psm)
    ctrl = _FakeController(snapshot_state)
    target.controller = ctrl
    return target


def _state_changing_events() -> list[dict[str, Any]]:
    """Events that include a run_archive_finalizing and script transitions."""
    return [
        _ev(1, stream="telemetry_in", device_id="PT-001", label="telem-1"),
        _ev(2, stream="system_event", event_type="script_started",
            name="static_fire", label="script-start"),
        _ev(3, stream="telemetry_in", device_id="PT-001", label="telem-3"),
        _ev(4, stream="system_event", event_type="script_held",
            label="script-held"),
        _ev(5, stream="system_event", event_type="script_continued",
            label="script-continued"),
        _ev(6, stream="system_event", event_type="script_stopped",
            name="static_fire", label="script-stopped"),
        _ev(6.5, stream="system_event", event_type="backend_health_changed",
            overall_status="warning",
            active_warnings=["bus: disconnected"], label="health-warn"),
        _ev(7, stream="system_event", event_type="run_archive_finalizing",
            reason="operator_stop", label="run-finalizing"),
    ]


_BASELINE_SNAPSHOT_STATE: dict[str, Any] = {
    "run": {"status": "running", "is_running": True, "mode": "live",
            "test_name": "test", "operator": "eric"},
    "script_runner": {"is_running": False, "name": "", "is_held": False,
                      "current_step_name": ""},
    "alarms": {"active_alarm_count": 0, "active_fault_count": 0},
    "health": {"overall_status": "ok", "active_warning_count": 0, "active_warnings": []},
    "mission_clock": {"seconds": 0.0, "state": "idle"},
    "recording_clock": {"active": True, "elapsed_seconds": 0.0},
}


class TestReconstructedStateReflectsReplay(unittest.TestCase):
    """After seek with tail replay containing state-changing system events,
    the reconstructed state must reflect the post-replay values, not just
    the snapshot baseline."""

    def test_run_status_changes_after_finalizing_event(self):
        events = _state_changing_events()
        ctx = _make_context(events, duration=8.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _make_target_with_controller(psm, _BASELINE_SNAPSHOT_STATE)

        # Seek to T=7.5 — tail replay includes run_archive_finalizing at T=7
        _handle_seek(target, 7.5)

        rs = psm.reconstructed_state
        self.assertEqual(rs["run_status"], "completed",
                         "run_status must reflect the finalizing event, not snapshot baseline")
        self.assertFalse(rs["run_is_running"])

    def test_script_started_then_stopped_reflected(self):
        events = _state_changing_events()
        ctx = _make_context(events, duration=8.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)

        # Seek to T=2.5 — after script_started at T=2
        target = _make_target_with_controller(psm, _BASELINE_SNAPSHOT_STATE)
        _handle_seek(target, 2.5)
        rs = psm.reconstructed_state
        self.assertTrue(rs["script_running"],
                        "script must be running after script_started event")
        self.assertEqual(rs["script_name"], "static_fire")

        # Seek to T=6.5 — after script_stopped at T=6
        _handle_seek(target, 6.5)
        rs = psm.reconstructed_state
        self.assertFalse(rs["script_running"],
                         "script must not be running after script_stopped event")

    def test_script_held_then_continued_reflected(self):
        events = _state_changing_events()
        ctx = _make_context(events, duration=8.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)

        # Seek to T=4.5 — after script_held at T=4
        target = _make_target_with_controller(psm, _BASELINE_SNAPSHOT_STATE)
        _handle_seek(target, 4.5)
        rs = psm.reconstructed_state
        self.assertTrue(rs["script_is_held"])

        # Seek to T=5.5 — after script_continued at T=5
        _handle_seek(target, 5.5)
        rs = psm.reconstructed_state
        self.assertFalse(rs["script_is_held"])

    def test_incremental_advance_updates_state(self):
        events = _state_changing_events()
        ctx = _make_context(events, duration=8.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _make_target_with_controller(psm, _BASELINE_SNAPSHOT_STATE)

        # Seek to T=1.5 (before script_started)
        _handle_seek(target, 1.5)
        rs = psm.reconstructed_state
        self.assertFalse(rs["script_running"])

        # Advance from T=1.5 to T=2.5 (crosses script_started at T=2)
        _handle_advance(target, 1.5, 2.5)
        rs = psm.reconstructed_state
        self.assertTrue(rs["script_running"],
                        "advance must update script state from replayed events")

    def test_seek_backward_resets_state_to_snapshot_baseline(self):
        """Seeking backward re-applies the T=0 snapshot, resetting state
        mutations from the previous forward seek's tail replay."""
        tmpdir = TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        snap_dir = Path(tmpdir.name)

        # Write a T=0 snapshot with baseline state
        snap_path = snap_dir / "000000.json"
        write_json(snap_path, {
            "recorded_at": _iso(0),
            "snapshot_index": 0,
            "state": dict(_BASELINE_SNAPSHOT_STATE),
        })
        snap_entry = {
            "path": str(snap_path),
            "snapshot_index": 0,
            "recorded_at": _iso(0),
            "relative_seconds": 0.0,
            "has_state": True,
        }

        events = _state_changing_events()
        ctx = _make_context(events, duration=8.0, snapshot_index=[snap_entry])
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _make_target_with_controller(psm, _BASELINE_SNAPSHOT_STATE)

        # Seek to T=7.5 — tail replay includes run_archive_finalizing at T=7
        _handle_seek(target, 7.5)
        self.assertEqual(psm.reconstructed_state["run_status"], "completed")

        # Seek backward to T=0.5 — snapshot at T=0 is re-applied, resetting
        # to baseline.  No state-changing events before T=1.
        _handle_seek(target, 0.5)
        self.assertEqual(psm.reconstructed_state["run_status"], "running")

    def test_health_status_changes_after_health_event(self):
        """backend_health_changed events update overall_health_status."""
        events = _state_changing_events()
        ctx = _make_context(events, duration=8.0)
        psm = PlaybackStateManager()
        psm.load_context(ctx)
        target = _make_target_with_controller(psm, _BASELINE_SNAPSHOT_STATE)

        # Seek to T=2.0 — before backend_health_changed at T=6.5
        _handle_seek(target, 2.0)
        rs = psm.reconstructed_state
        self.assertEqual(rs["overall_health_status"], "ok")
        self.assertEqual(rs["active_warning_count"], 0)

        # Seek to T=6.8 — after backend_health_changed at T=6.5
        _handle_seek(target, 6.8)
        rs = psm.reconstructed_state
        self.assertEqual(rs["overall_health_status"], "warning")
        self.assertEqual(rs["active_warning_count"], 1)
