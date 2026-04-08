"""Tests for PlaybackStateManager - the single authoritative playback state owner.

Covers: context loading, position tracking, play/pause/toggle engine,
speed control, advance time computation, wall-time utility, edge cases,
and single-update-path semantics for seek/advance fan-out.
"""
from __future__ import annotations

import time
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, call

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip

psm_mod = import_module_or_skip("gui.playback_state_manager")
window_host = import_module_or_skip("gui.window_host")
PlaybackRunContext = psm_mod.PlaybackRunContext
PlaybackStateManager = psm_mod.PlaybackStateManager


def _make_context(
    *,
    duration: float = 60.0,
    start_iso: str = "2026-01-01T00:00:00+00:00",
    n_events: int = 3,
    n_snapshots: int = 2,
) -> PlaybackRunContext:
    start_dt = datetime.fromisoformat(start_iso)
    end_dt = start_dt + timedelta(seconds=duration)
    events = [{"recorded_at": (start_dt + timedelta(seconds=i * 10)).isoformat(), "label": f"e{i}"} for i in range(n_events)]
    time_keys = [start_dt.timestamp() + i * 10 for i in range(n_events)]
    snapshots = [{"path": f"/tmp/snap_{i:06d}.json", "snapshot_index": i, "relative_seconds": float(i * 30)} for i in range(n_snapshots)]
    return PlaybackRunContext(
        run_id="test-run-001",
        history_dir="/tmp/test-run",
        playback_source="native",
        metadata={"run_id": "test-run-001", "test_name": "unit test"},
        start_dt=start_dt,
        end_dt=end_dt,
        duration_seconds=duration,
        snapshot_index=snapshots,
        snapshot_files=[f"/tmp/snap_{i:06d}.json" for i in range(n_snapshots)],
        merged_events=list(events),
        seek_events=list(events),
        event_time_keys=list(time_keys),
        initial_snapshot={"state": {"device_states": {}}},
    )


class TestPlaybackRunContext(unittest.TestCase):
    def test_create_with_required_fields(self):
        ctx = _make_context()
        self.assertEqual(ctx.run_id, "test-run-001")
        self.assertEqual(ctx.duration_seconds, 60.0)
        self.assertEqual(len(ctx.merged_events), 3)
        self.assertEqual(len(ctx.snapshot_index), 2)

    def test_defaults_are_empty(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ctx = PlaybackRunContext(
            run_id="r", history_dir="/tmp", playback_source="native",
            metadata={}, start_dt=start, end_dt=start, duration_seconds=0.0,
        )
        self.assertEqual(ctx.snapshot_index, [])
        self.assertEqual(ctx.merged_events, [])
        self.assertEqual(ctx.event_time_keys, [])
        self.assertIsNone(ctx.initial_snapshot)


class TestPlaybackStateManagerInit(unittest.TestCase):
    def test_initial_state(self):
        mgr = PlaybackStateManager()
        self.assertIsNone(mgr.context)
        self.assertEqual(mgr.position_seconds, 0.0)
        self.assertEqual(mgr.last_event_index, 0)
        self.assertFalse(mgr.is_playing)
        self.assertEqual(mgr.speed, 1.0)

    def test_properties_without_context(self):
        mgr = PlaybackStateManager()
        self.assertEqual(mgr.duration_seconds, 0.0)
        self.assertIsNone(mgr.start_dt)
        self.assertIsNone(mgr.end_dt)
        self.assertEqual(mgr.snapshot_index, [])
        self.assertEqual(mgr.seek_events, [])
        self.assertEqual(mgr.event_time_keys, [])
        self.assertEqual(mgr.merged_events, [])
        self.assertIsNone(mgr.run_id)


class TestLoadContext(unittest.TestCase):
    def test_load_populates_context(self):
        mgr = PlaybackStateManager()
        ctx = _make_context(duration=120.0)
        mgr.load_context(ctx)
        self.assertIs(mgr.context, ctx)
        self.assertEqual(mgr.duration_seconds, 120.0)
        self.assertEqual(mgr.run_id, "test-run-001")
        self.assertEqual(len(mgr.seek_events), 3)

    def test_load_resets_runtime_state(self):
        mgr = PlaybackStateManager()
        mgr.position_seconds = 45.0
        mgr.last_event_index = 100
        mgr.is_playing = True
        mgr.speed = 4.0
        mgr.load_context(_make_context())
        self.assertEqual(mgr.position_seconds, 0.0)
        self.assertEqual(mgr.last_event_index, 0)
        self.assertFalse(mgr.is_playing)
        self.assertEqual(mgr.speed, 1.0)


class TestPositionControl(unittest.TestCase):
    def setUp(self):
        self.mgr = PlaybackStateManager()
        self.mgr.load_context(_make_context(duration=60.0))

    def test_set_position(self):
        self.mgr.set_position(30.0)
        self.assertEqual(self.mgr.position_seconds, 30.0)

    def test_set_position_clamps_negative(self):
        self.mgr.set_position(-5.0)
        self.assertEqual(self.mgr.position_seconds, 0.0)

    def test_update_after_seek(self):
        self.mgr.update_after_seek(position=25.0, event_index=42)
        self.assertEqual(self.mgr.position_seconds, 25.0)
        self.assertEqual(self.mgr.last_event_index, 42)
        self.assertEqual(self.mgr.last_applied_time, 25.0)

    def test_update_after_advance(self):
        self.mgr.update_after_advance(position=10.0, event_index=7)
        self.assertEqual(self.mgr.position_seconds, 10.0)
        self.assertEqual(self.mgr.last_event_index, 7)
        self.assertEqual(self.mgr.last_applied_time, 10.0)


class TestPlayPauseEngine(unittest.TestCase):
    def setUp(self):
        self.mgr = PlaybackStateManager()
        self.mgr.load_context(_make_context(duration=60.0))

    def test_start_playing_from_zero(self):
        result = self.mgr.start_playing()
        self.assertTrue(result)
        self.assertTrue(self.mgr.is_playing)

    def test_start_playing_at_end_returns_false(self):
        self.mgr.set_position(60.0)
        result = self.mgr.start_playing()
        self.assertFalse(result)
        self.assertFalse(self.mgr.is_playing)

    def test_start_playing_when_already_playing(self):
        self.mgr.start_playing()
        result = self.mgr.start_playing()
        self.assertTrue(result)
        self.assertTrue(self.mgr.is_playing)

    def test_pause_when_not_playing(self):
        pos = self.mgr.pause()
        self.assertEqual(pos, 0.0)
        self.assertFalse(self.mgr.is_playing)

    def test_pause_computes_position(self):
        self.mgr.set_position(10.0)
        mono_base = time.monotonic()
        with patch("gui.playback_state_manager.time") as mock_time:
            mock_time.monotonic.return_value = mono_base
            self.mgr.start_playing()
            mock_time.monotonic.return_value = mono_base + 5.0
            pos = self.mgr.pause()
        self.assertAlmostEqual(pos, 15.0, places=1)
        self.assertFalse(self.mgr.is_playing)

    def test_pause_clamps_to_duration(self):
        self.mgr.set_position(55.0)
        mono_base = time.monotonic()
        with patch("gui.playback_state_manager.time") as mock_time:
            mock_time.monotonic.return_value = mono_base
            self.mgr.start_playing()
            mock_time.monotonic.return_value = mono_base + 10.0
            pos = self.mgr.pause()
        self.assertAlmostEqual(pos, 60.0, places=1)

    def test_toggle_playing(self):
        result = self.mgr.toggle_playing()
        self.assertTrue(result)
        self.assertTrue(self.mgr.is_playing)
        result = self.mgr.toggle_playing()
        self.assertFalse(result)
        self.assertFalse(self.mgr.is_playing)


class TestComputeAdvanceTime(unittest.TestCase):
    def setUp(self):
        self.mgr = PlaybackStateManager()
        self.mgr.load_context(_make_context(duration=60.0))

    def test_when_paused_returns_position(self):
        self.mgr.set_position(25.0)
        self.assertEqual(self.mgr.compute_advance_time(), 25.0)

    def test_when_playing_returns_elapsed(self):
        self.mgr.set_position(10.0)
        mono_base = time.monotonic()
        with patch("gui.playback_state_manager.time") as mock_time:
            mock_time.monotonic.return_value = mono_base
            self.mgr.start_playing()
            mock_time.monotonic.return_value = mono_base + 3.0
            result = self.mgr.compute_advance_time()
        self.assertAlmostEqual(result, 13.0, places=1)

    def test_clamps_to_duration(self):
        self.mgr.set_position(58.0)
        mono_base = time.monotonic()
        with patch("gui.playback_state_manager.time") as mock_time:
            mock_time.monotonic.return_value = mono_base
            self.mgr.start_playing()
            mock_time.monotonic.return_value = mono_base + 5.0
            result = self.mgr.compute_advance_time()
        self.assertAlmostEqual(result, 60.0, places=1)


class TestSpeedControl(unittest.TestCase):
    def setUp(self):
        self.mgr = PlaybackStateManager()
        self.mgr.load_context(_make_context(duration=60.0))

    def test_set_speed(self):
        self.mgr.set_speed(2.0)
        self.assertEqual(self.mgr.speed, 2.0)

    def test_set_speed_clamps_minimum(self):
        self.mgr.set_speed(0.001)
        self.assertAlmostEqual(self.mgr.speed, 0.01)

    def test_step_speed_up(self):
        result = self.mgr.step_speed(1)  # 1.0 -> 2.0
        self.assertEqual(result, 2.0)
        self.assertEqual(self.mgr.speed, 2.0)

    def test_step_speed_down(self):
        result = self.mgr.step_speed(-1)  # 1.0 -> 0.5
        self.assertEqual(result, 0.5)

    def test_step_speed_clamps_at_min(self):
        self.mgr.set_speed(0.25)
        result = self.mgr.step_speed(-1)  # already at minimum
        self.assertEqual(result, 0.25)

    def test_step_speed_clamps_at_max(self):
        self.mgr.set_speed(4.0)
        result = self.mgr.step_speed(1)  # already at maximum
        self.assertEqual(result, 4.0)

    def test_speed_affects_advance_time(self):
        self.mgr.set_speed(2.0)
        self.mgr.set_position(10.0)
        mono_base = time.monotonic()
        with patch("gui.playback_state_manager.time") as mock_time:
            mock_time.monotonic.return_value = mono_base
            self.mgr.start_playing()
            mock_time.monotonic.return_value = mono_base + 5.0
            result = self.mgr.compute_advance_time()
        # 10 + (5 * 2.0) = 20.0
        self.assertAlmostEqual(result, 20.0, places=1)

    def test_set_speed_reanchors_when_playing(self):
        self.mgr.set_position(10.0)
        mono_base = time.monotonic()
        with patch("gui.playback_state_manager.time") as mock_time:
            mock_time.monotonic.return_value = mono_base
            self.mgr.start_playing()
            mock_time.monotonic.return_value = mono_base + 5.0
            # At this point, position should be ~15.0 (10 + 5*1.0)
            self.mgr.set_speed(2.0)
            # After re-anchor, position = 15.0, new mono_start = mono_base+5
            mock_time.monotonic.return_value = mono_base + 8.0
            result = self.mgr.compute_advance_time()
        # 15 + (3 * 2.0) = 21.0
        self.assertAlmostEqual(result, 21.0, places=1)


class TestAtEnd(unittest.TestCase):
    def test_not_at_end(self):
        mgr = PlaybackStateManager()
        mgr.load_context(_make_context(duration=60.0))
        mgr.set_position(30.0)
        self.assertFalse(mgr.at_end())

    def test_at_end(self):
        mgr = PlaybackStateManager()
        mgr.load_context(_make_context(duration=60.0))
        mgr.set_position(60.0)
        self.assertTrue(mgr.at_end())

    def test_zero_duration_never_at_end(self):
        mgr = PlaybackStateManager()
        mgr.load_context(_make_context(duration=0.0))
        self.assertFalse(mgr.at_end())


class TestWallTime(unittest.TestCase):
    def test_wall_time_at_current_position(self):
        mgr = PlaybackStateManager()
        ctx = _make_context(start_iso="2026-01-01T00:00:00+00:00", duration=60.0)
        mgr.load_context(ctx)
        mgr.set_position(30.0)
        wt = mgr.wall_time_for_position()
        expected = datetime(2026, 1, 1, 0, 0, 30, tzinfo=timezone.utc)
        self.assertEqual(wt, expected)

    def test_wall_time_explicit_position(self):
        mgr = PlaybackStateManager()
        ctx = _make_context(start_iso="2026-01-01T00:00:00+00:00", duration=60.0)
        mgr.load_context(ctx)
        wt = mgr.wall_time_for_position(45.0)
        expected = datetime(2026, 1, 1, 0, 0, 45, tzinfo=timezone.utc)
        self.assertEqual(wt, expected)

    def test_wall_time_no_context(self):
        mgr = PlaybackStateManager()
        self.assertIsNone(mgr.wall_time_for_position())


class TestContextPropertyAccess(unittest.TestCase):
    def test_properties_with_context(self):
        mgr = PlaybackStateManager()
        ctx = _make_context(duration=120.0, n_events=5, n_snapshots=3)
        mgr.load_context(ctx)
        self.assertEqual(mgr.duration_seconds, 120.0)
        self.assertEqual(mgr.start_dt, ctx.start_dt)
        self.assertEqual(mgr.end_dt, ctx.end_dt)
        self.assertEqual(len(mgr.snapshot_index), 3)
        self.assertEqual(len(mgr.seek_events), 5)
        self.assertEqual(len(mgr.event_time_keys), 5)
        self.assertEqual(len(mgr.merged_events), 5)
        self.assertEqual(mgr.run_id, "test-run-001")


# ---------------------------------------------------------------------------
# Single-update-path tests: verify _apply_exact_playback_seek_state uses
# set_playback_time as the single coordinated update entry point and does
# NOT separately call timeline/console on targets that have it.
# ---------------------------------------------------------------------------

_apply = window_host._apply_exact_playback_seek_state


class _MockTarget:
    """Simulates a window target with controllable presence of update methods."""

    def __init__(self, *, has_set_playback_time=False):
        self._backend_playback_clock = {"position_seconds": 0.0}
        self._timeline_calls: list[float] = []
        self._console_calls: list[float] = []
        self._set_pt_calls: list[float] = []

        class _Timeline:
            def __init__(inner_self):
                inner_self.calls = self._timeline_calls
            def set_current_time(inner_self, t):
                inner_self.calls.append(t)

        class _Console:
            def __init__(inner_self):
                inner_self.calls = self._console_calls
            def set_playback_time(inner_self, t):
                inner_self.calls.append(t)

        self.timeline = _Timeline()
        self.console = _Console()

        if has_set_playback_time:
            def _spt(seek_time):
                self._set_pt_calls.append(seek_time)
            self.set_playback_time = _spt


class TestApplyExactPlaybackSeekState(unittest.TestCase):
    """Verify _apply_exact_playback_seek_state uses one update path per target."""

    def test_target_with_set_playback_time_gets_single_call(self):
        """When a target has set_playback_time, only that method should be
        called — timeline and console should NOT be called separately."""
        target = _MockTarget(has_set_playback_time=True)

        # Build a minimal facade that exposes the target as its controller
        facade = type("Facade", (), {
            "controller": target,
            "scada": None,
            "script": None,
            "_backend_playback_clock": None,
        })()

        _apply(facade, 42.5)

        # set_playback_time should be called exactly once on the target
        self.assertEqual(target._set_pt_calls, [42.5])
        # timeline and console should NOT have been called directly by _retime_target
        self.assertEqual(target._timeline_calls, [])
        self.assertEqual(target._console_calls, [])

    def test_target_without_set_playback_time_gets_individual_calls(self):
        """When a target lacks set_playback_time (e.g. ScadaWindow), fall back
        to individual timeline + console calls."""
        target = _MockTarget(has_set_playback_time=False)

        facade = type("Facade", (), {
            "controller": None,
            "scada": target,
            "script": None,
            "_backend_playback_clock": None,
        })()

        _apply(facade, 10.0)

        self.assertEqual(target._set_pt_calls, [])
        self.assertEqual(target._timeline_calls, [10.0])
        self.assertEqual(target._console_calls, [10.0])

    def test_backend_playback_clock_updated_on_target(self):
        """_backend_playback_clock.position_seconds should be updated
        regardless of which update path is used."""
        target = _MockTarget(has_set_playback_time=True)
        facade = type("Facade", (), {
            "controller": target,
            "scada": None,
            "script": None,
            "_backend_playback_clock": None,
        })()

        _apply(facade, 25.0)

        self.assertEqual(
            target._backend_playback_clock["position_seconds"], 25.0
        )
