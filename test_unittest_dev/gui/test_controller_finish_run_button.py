"""Regression tests for commit-1: restore finish-run controls after
controller respawn during recording.

Verifies that:
- The Finish Run button is hidden by default (no active run).
- ``apply_backend_state_snapshot`` shows the button when ``run.is_running``
  is True in the authoritative backend snapshot.
- The button hides again when the run is no longer active.
- Clicking the button calls the backend-facing ``finish_backend_run`` path.
- The button is inert in playback mode and safe if the bridge is not attached.
"""

from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import get_qapplication, import_module_or_skip


controller_module = import_module_or_skip("gui.controller_window")
ControllerWindow = controller_module.ControllerWindow


def _make_snapshot(*, is_running: bool) -> dict:
    """Minimal backend state snapshot with the given run state."""
    return {
        "run": {
            "active_run_id": "run_001" if is_running else None,
            "is_running": is_running,
            "status": "running" if is_running else "completed",
        },
        "recording_clock": {
            "active": is_running,
            "status": "recording" if is_running else "stopped",
            "display_text": "Recording: 0m 00s" if is_running else "Not Recording",
            "accent": "recording" if is_running else "neutral",
            "elapsed_seconds": 0.0,
        },
        "mission_clock": {"label": "T+", "state": "idle", "seconds": 0.0},
        "playback_clock": {"active": False, "status": "idle"},
    }


class TestControllerFinishRunButton(unittest.TestCase):
    """Verify the Finish Run button shows/hides based on backend run state.

    Uses ``isHidden()`` to check the widget's own visibility flag regardless
    of whether the parent window is shown (correct for offscreen Qt tests).
    """

    @classmethod
    def setUpClass(cls):
        cls.app = get_qapplication()

    def _make_window(self, *, playback_mode=False):
        window = ControllerWindow(playback_mode=playback_mode)
        self.addCleanup(window.close)
        return window

    # -- visibility -----------------------------------------------------------

    def test_button_hidden_by_default(self):
        window = self._make_window()
        self.assertTrue(window.btn_finish_run.isHidden())

    def test_button_shown_when_run_active(self):
        window = self._make_window()
        window.apply_backend_state_snapshot(_make_snapshot(is_running=True))
        self.assertFalse(window.btn_finish_run.isHidden())

    def test_button_hidden_when_run_stops(self):
        window = self._make_window()
        window.apply_backend_state_snapshot(_make_snapshot(is_running=True))
        self.assertFalse(window.btn_finish_run.isHidden())
        window.apply_backend_state_snapshot(_make_snapshot(is_running=False))
        self.assertTrue(window.btn_finish_run.isHidden())

    def test_snapshot_without_run_key_hides_button(self):
        window = self._make_window()
        window.apply_backend_state_snapshot(_make_snapshot(is_running=True))
        self.assertFalse(window.btn_finish_run.isHidden())
        window.apply_backend_state_snapshot({"recording_clock": {"active": False}})
        self.assertTrue(window.btn_finish_run.isHidden())

    # -- click behaviour ------------------------------------------------------

    def test_click_calls_finish_backend_run(self):
        window = self._make_window()
        window.apply_backend_state_snapshot(_make_snapshot(is_running=True))

        calls: list[str] = []
        window.finish_backend_run = lambda reason="operator_stop": calls.append(reason)

        window.btn_finish_run.click()
        self.assertEqual(calls, ["operator_stop"])

    def test_click_noop_in_playback_mode(self):
        window = self._make_window(playback_mode=True)
        window.apply_backend_state_snapshot(_make_snapshot(is_running=True))

        calls: list[str] = []
        window.finish_backend_run = lambda reason="operator_stop": calls.append(reason)
        window.btn_finish_run.click()
        self.assertEqual(calls, [], "Finish run must not fire in playback mode")

    def test_click_safe_without_bridge(self):
        """Clicking when finish_backend_run is not injected must not crash."""
        window = self._make_window()
        window.apply_backend_state_snapshot(_make_snapshot(is_running=True))
        if hasattr(window, "finish_backend_run"):
            delattr(window, "finish_backend_run")
        window.btn_finish_run.click()  # should not raise

    # -- simulated respawn scenario -------------------------------------------

    def test_respawn_scenario_button_appears_from_backend_state(self):
        """Simulate: fresh window receives a snapshot where a run is already
        active (as happens after supervisor respawn).  Verify the Finish Run
        button is immediately available."""
        window = self._make_window()
        self.assertTrue(window.btn_finish_run.isHidden(), "Hidden before any snapshot")

        window.apply_backend_state_snapshot(_make_snapshot(is_running=True))
        self.assertFalse(window.btn_finish_run.isHidden(), "Visible after recording snapshot")


if __name__ == "__main__":
    unittest.main()
