"""Regression tests for commit-2: fix recording clock to track authoritative
run timing across reconnects.

Verifies that:
- ``_parse_recording_start_time`` correctly extracts a datetime from a
  recording_clock snapshot section when active and well-formed.
- The parsed start time is stored and cleared by
  ``apply_backend_state_snapshot``.
- ``_refresh_aux_clock_display`` computes non-zero elapsed time locally
  instead of displaying a stale snapshot string.
- After a simulated respawn (fresh window + snapshot with a past start time),
  the display shows correct elapsed time rather than resetting to zero.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone, timedelta

from test_unittest_dev.helpers.repo_test_tools import get_qapplication, import_module_or_skip


controller_module = import_module_or_skip("gui.controller_window")
ControllerWindow = controller_module.ControllerWindow


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _make_recording_snapshot(*, started_seconds_ago: float) -> dict:
    """Build a snapshot where recording started ``started_seconds_ago`` in the past."""
    started = datetime.now(timezone.utc) - timedelta(seconds=started_seconds_ago)
    return {
        "run": {
            "active_run_id": "run_clock_test",
            "is_running": True,
            "status": "running",
            "last_started_wall_time": _iso_z(started),
        },
        "recording_clock": {
            "active": True,
            "status": "recording",
            "started_wall_time": _iso_z(started),
            "stopped_wall_time": None,
            "elapsed_seconds": started_seconds_ago,
            "display_text": f"Recording: {int(started_seconds_ago // 60)}m {int(started_seconds_ago % 60):02d}s",
            "accent": "recording",
        },
        "mission_clock": {"label": "T+", "state": "idle", "seconds": 0.0},
        "playback_clock": {"active": False, "status": "idle"},
    }


def _make_idle_snapshot() -> dict:
    return {
        "run": {"active_run_id": None, "is_running": False, "status": "idle"},
        "recording_clock": {
            "active": False,
            "status": "idle",
            "started_wall_time": None,
            "stopped_wall_time": None,
            "elapsed_seconds": 0.0,
            "display_text": "Not Recording",
            "accent": "neutral",
        },
        "mission_clock": {"label": "T+", "state": "idle", "seconds": 0.0},
        "playback_clock": {"active": False, "status": "idle"},
    }


class TestParseRecordingStartTime(unittest.TestCase):
    """Unit tests for ControllerWindow._parse_recording_start_time."""

    def test_returns_datetime_when_active_with_z_suffix(self):
        result = ControllerWindow._parse_recording_start_time(
            {"active": True, "started_wall_time": "2026-03-15T10:30:00.000Z"}
        )
        self.assertIsInstance(result, datetime)
        self.assertEqual(result.year, 2026)
        self.assertEqual(result.month, 3)
        self.assertEqual(result.hour, 10)

    def test_returns_datetime_when_active_with_offset(self):
        result = ControllerWindow._parse_recording_start_time(
            {"active": True, "started_wall_time": "2026-03-15T10:30:00+00:00"}
        )
        self.assertIsInstance(result, datetime)

    def test_returns_none_when_inactive(self):
        result = ControllerWindow._parse_recording_start_time(
            {"active": False, "started_wall_time": "2026-03-15T10:30:00.000Z"}
        )
        self.assertIsNone(result)

    def test_returns_none_when_no_timestamp(self):
        self.assertIsNone(ControllerWindow._parse_recording_start_time({"active": True}))

    def test_returns_none_when_timestamp_is_none(self):
        self.assertIsNone(
            ControllerWindow._parse_recording_start_time(
                {"active": True, "started_wall_time": None}
            )
        )

    def test_returns_none_for_non_dict(self):
        self.assertIsNone(ControllerWindow._parse_recording_start_time(None))
        self.assertIsNone(ControllerWindow._parse_recording_start_time("not a dict"))

    def test_returns_none_for_malformed_timestamp(self):
        self.assertIsNone(
            ControllerWindow._parse_recording_start_time(
                {"active": True, "started_wall_time": "not-a-date"}
            )
        )


class TestRecordingClockDisplay(unittest.TestCase):
    """Integration tests for recording clock display in ControllerWindow."""

    @classmethod
    def setUpClass(cls):
        cls.app = get_qapplication()

    def _make_window(self):
        window = ControllerWindow(playback_mode=False)
        window.display_timer.stop()  # Prevent timer interference during tests.
        self.addCleanup(window.close)
        return window

    # -- _recording_started_dt lifecycle -------------------------------------

    def test_started_dt_populated_from_active_snapshot(self):
        window = self._make_window()
        window.apply_backend_state_snapshot(
            _make_recording_snapshot(started_seconds_ago=30.0)
        )
        self.assertIsNotNone(window._recording_started_dt)
        self.assertIsInstance(window._recording_started_dt, datetime)

    def test_started_dt_cleared_when_recording_stops(self):
        window = self._make_window()
        window.apply_backend_state_snapshot(
            _make_recording_snapshot(started_seconds_ago=10.0)
        )
        self.assertIsNotNone(window._recording_started_dt)
        window.apply_backend_state_snapshot(_make_idle_snapshot())
        self.assertIsNone(window._recording_started_dt)

    # -- display output ------------------------------------------------------

    def test_active_recording_shows_nonzero_elapsed(self):
        window = self._make_window()
        window.apply_backend_state_snapshot(
            _make_recording_snapshot(started_seconds_ago=125.0)
        )
        window._refresh_aux_clock_display()
        text = window.aux_time_label.text()
        self.assertIn("Recording:", text)
        self.assertNotEqual(text, "Recording: 0m 00s",
                            "Clock must not be stuck at zero")

    def test_idle_shows_not_recording(self):
        window = self._make_window()
        window.apply_backend_state_snapshot(_make_idle_snapshot())
        window._refresh_aux_clock_display()
        self.assertEqual(window.aux_time_label.text(), "Not Recording")

    def test_fallback_to_display_text_without_start_time(self):
        """If active but started_wall_time is missing, fall back to
        backend-provided display_text."""
        window = self._make_window()
        snapshot = {
            "recording_clock": {
                "active": True,
                "display_text": "Recording: 5m 00s",
                "started_wall_time": None,
            },
            "mission_clock": {"label": "T+", "state": "idle", "seconds": 0.0},
            "playback_clock": {"active": False, "status": "idle"},
        }
        window.apply_backend_state_snapshot(snapshot)
        window._refresh_aux_clock_display()
        self.assertEqual(window.aux_time_label.text(), "Recording: 5m 00s")

    # -- simulated respawn scenario ------------------------------------------

    def test_respawn_shows_correct_elapsed_not_zero(self):
        """Fresh window receives snapshot where recording started 60s ago.
        Verify the clock shows ~1m elapsed, not 0m 00s."""
        window = self._make_window()
        window.apply_backend_state_snapshot(
            _make_recording_snapshot(started_seconds_ago=60.0)
        )
        window._refresh_aux_clock_display()
        text = window.aux_time_label.text()
        self.assertIn("Recording:", text)
        self.assertNotEqual(text, "Recording: 0m 00s")


if __name__ == "__main__":
    unittest.main()
