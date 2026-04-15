"""Tests for backend-authoritative controller header badge refresh.

Verifies that ``_refresh_badges_from_snapshot`` correctly maps backend
snapshot state to the Status, Script, and Health badge widgets, and that
playback mode is not affected by the live-mode refresh path.
"""

from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import get_qapplication, import_module_or_skip


controller_module = import_module_or_skip("gui.controller_window")
ControllerWindow = controller_module.ControllerWindow


def _make_snapshot(
    *,
    abort_latched: bool = False,
    run_is_running: bool = False,
    script_is_running: bool = False,
    script_is_held: bool = False,
    last_exit_status: str | None = None,
    health_overall: str = "ok",
) -> dict:
    """Build a minimal backend snapshot for badge testing."""
    return {
        "abort": {
            "abort_latched": abort_latched,
            "latched_at": None,
            "latched_by": None,
            "latched_request_id": None,
        },
        "run": {
            "active_run_id": "run-1" if run_is_running else None,
            "is_running": run_is_running,
            "status": "running" if run_is_running else "idle",
        },
        "script_runner": {
            "is_running": script_is_running,
            "is_held": script_is_held,
            "last_exit_status": last_exit_status,
        },
        "health": {
            "overall_status": health_overall,
        },
        "recording_clock": {},
        "mission_clock": {},
        "playback_clock": {},
    }


class TestControllerBadgeRefresh(unittest.TestCase):
    """Verify _refresh_badges_from_snapshot badge derivation logic."""

    @classmethod
    def setUpClass(cls):
        cls.app = get_qapplication()

    def _make_live_window(self) -> ControllerWindow:
        win = ControllerWindow(playback_mode=False)
        return win

    def _make_playback_window(self) -> ControllerWindow:
        win = ControllerWindow(playback_mode=True)
        return win

    def test_idle_state(self):
        win = self._make_live_window()
        snap = _make_snapshot()
        win._refresh_badges_from_snapshot(snap)
        self.assertEqual(win.status_badge.text(), "Idle")
        self.assertEqual(win.script_badge.text(), "Idle")
        self.assertEqual(win.health_badge.text(), "OK")

    def test_run_active_no_script(self):
        win = self._make_live_window()
        snap = _make_snapshot(run_is_running=True)
        win._refresh_badges_from_snapshot(snap)
        self.assertEqual(win.status_badge.text(), "Normal")
        self.assertEqual(win.script_badge.text(), "Idle")

    def test_script_running(self):
        win = self._make_live_window()
        snap = _make_snapshot(run_is_running=True, script_is_running=True)
        win._refresh_badges_from_snapshot(snap)
        self.assertEqual(win.status_badge.text(), "Normal")
        self.assertEqual(win.script_badge.text(), "Running")

    def test_script_held(self):
        win = self._make_live_window()
        snap = _make_snapshot(
            run_is_running=True, script_is_running=True, script_is_held=True
        )
        win._refresh_badges_from_snapshot(snap)
        self.assertEqual(win.script_badge.text(), "Paused")

    def test_abort_latched(self):
        win = self._make_live_window()
        snap = _make_snapshot(abort_latched=True, run_is_running=True)
        win._refresh_badges_from_snapshot(snap)
        self.assertEqual(win.status_badge.text(), "Abort")

    def test_abort_latched_script_stopped(self):
        win = self._make_live_window()
        snap = _make_snapshot(
            abort_latched=True, run_is_running=True, script_is_running=False
        )
        win._refresh_badges_from_snapshot(snap)
        self.assertEqual(win.status_badge.text(), "Abort")
        self.assertEqual(win.script_badge.text(), "Idle")

    def test_health_warning(self):
        win = self._make_live_window()
        snap = _make_snapshot(health_overall="warning")
        win._refresh_badges_from_snapshot(snap)
        self.assertEqual(win.health_badge.text(), "Attention")

    def test_health_error(self):
        win = self._make_live_window()
        snap = _make_snapshot(health_overall="error")
        win._refresh_badges_from_snapshot(snap)
        self.assertEqual(win.health_badge.text(), "Alarm")

    def test_script_last_exit_completed_shows_idle(self):
        win = self._make_live_window()
        snap = _make_snapshot(
            run_is_running=True, script_is_running=False, last_exit_status="completed"
        )
        win._refresh_badges_from_snapshot(snap)
        self.assertEqual(win.script_badge.text(), "Idle")

    def test_script_last_exit_failed(self):
        win = self._make_live_window()
        snap = _make_snapshot(
            run_is_running=True, script_is_running=False, last_exit_status="failed"
        )
        win._refresh_badges_from_snapshot(snap)
        self.assertEqual(win.script_badge.text(), "Failed")

    def test_playback_mode_skips_refresh(self):
        win = self._make_playback_window()
        # Set badges to known state
        win.set_status("hold")
        win.set_script_state("pause")
        win.set_health("ok")

        snap = _make_snapshot(abort_latched=True, script_is_running=True)
        win._refresh_badges_from_snapshot(snap)

        # Playback mode should NOT have changed the badges
        self.assertEqual(win.status_badge.text(), "Hold")
        self.assertEqual(win.script_badge.text(), "Paused")
        self.assertEqual(win.health_badge.text(), "OK")

    def test_missing_abort_section_defaults_gracefully(self):
        win = self._make_live_window()
        snap = _make_snapshot()
        del snap["abort"]
        win._refresh_badges_from_snapshot(snap)
        # Should not crash, status should default to idle
        self.assertEqual(win.status_badge.text(), "Idle")

    def test_missing_script_runner_section(self):
        win = self._make_live_window()
        snap = _make_snapshot()
        del snap["script_runner"]
        # Set badge to running first
        win.set_script_state("running")
        win._refresh_badges_from_snapshot(snap)
        # Without script_runner section, badge should remain unchanged
        self.assertEqual(win.script_badge.text(), "Running")

    def test_health_unknown_resets_to_default(self):
        win = self._make_live_window()
        # Set health to alarm first
        win.set_health("alarm")
        self.assertEqual(win.health_badge.text(), "Alarm")

        snap = _make_snapshot(health_overall="unknown")
        win._refresh_badges_from_snapshot(snap)
        # Should reset to the default badge ("--")
        self.assertEqual(win.health_badge.text(), "--")

    def test_health_unrecognized_resets_to_default(self):
        win = self._make_live_window()
        win.set_health("alarm")

        snap = _make_snapshot(health_overall="something_weird")
        win._refresh_badges_from_snapshot(snap)
        self.assertEqual(win.health_badge.text(), "--")


class TestControllerIncrementalScriptBadge(unittest.TestCase):
    """Verify handle_script_status incremental badge mapping."""

    @classmethod
    def setUpClass(cls):
        cls.app = get_qapplication()

    def _make_live_window(self) -> ControllerWindow:
        return ControllerWindow(playback_mode=False)

    def test_started_shows_running(self):
        win = self._make_live_window()
        win.handle_script_status({"status": "started"})
        self.assertEqual(win.script_badge.text(), "Running")

    def test_running_shows_running(self):
        win = self._make_live_window()
        win.handle_script_status({"status": "running"})
        self.assertEqual(win.script_badge.text(), "Running")

    def test_held_shows_paused(self):
        win = self._make_live_window()
        win.handle_script_status({"status": "held"})
        self.assertEqual(win.script_badge.text(), "Paused")

    def test_failed_shows_failed(self):
        win = self._make_live_window()
        win.handle_script_status({"status": "failed"})
        self.assertEqual(win.script_badge.text(), "Failed")

    def test_stopped_shows_idle(self):
        win = self._make_live_window()
        win.set_script_state("running")
        win.handle_script_status({"status": "stopped"})
        self.assertEqual(win.script_badge.text(), "Idle")

    def test_completed_shows_idle(self):
        win = self._make_live_window()
        win.set_script_state("running")
        win.handle_script_status({"status": "completed"})
        self.assertEqual(win.script_badge.text(), "Idle")

    def test_exited_shows_idle(self):
        win = self._make_live_window()
        win.set_script_state("running")
        win.handle_script_status({"status": "exited"})
        self.assertEqual(win.script_badge.text(), "Idle")

    def test_playback_mode_does_not_update_badge(self):
        win = ControllerWindow(playback_mode=True)
        win.set_script_state("pause")
        win.handle_script_status({"status": "running"})
        self.assertEqual(win.script_badge.text(), "Paused")


if __name__ == "__main__":
    unittest.main()
