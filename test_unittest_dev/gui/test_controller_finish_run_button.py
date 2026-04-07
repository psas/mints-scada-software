"""Tests for Start Recording / Stop Recording controls in the live
controller window.

Verifies that:
- Start Recording is enabled and Stop Recording is disabled by default.
- ``apply_backend_state_snapshot`` disables Start and enables Stop when
  ``run.is_running`` is True.
- After the run finishes, both buttons are disabled when session is consumed.
- Start Recording text changes to "Recording Done" when session is consumed.
- Clicking Start calls ``start_backend_run``.
- Clicking Stop calls ``finish_backend_run``.
- Buttons are not created in playback mode.
- Clicking is safe when the bridge is not attached.
"""

from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import get_qapplication, import_module_or_skip


controller_module = import_module_or_skip("gui.controller_window")
ControllerWindow = controller_module.ControllerWindow


def _make_snapshot(*, is_running: bool, consumed: bool = False) -> dict:
    """Minimal backend state snapshot with the given run state."""
    return {
        "run": {
            "active_run_id": "run_001" if is_running else None,
            "is_running": is_running,
            "recording_session_consumed": consumed,
            "status": "running" if is_running else ("completed" if consumed else "idle"),
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


class TestControllerRecordingButtons(unittest.TestCase):
    """Verify Start/Stop Recording button states based on backend run state."""

    @classmethod
    def setUpClass(cls):
        cls.app = get_qapplication()

    def _make_window(self, *, playback_mode=False):
        window = ControllerWindow(playback_mode=playback_mode)
        self.addCleanup(window.close)
        return window

    # -- initial state --------------------------------------------------------

    def test_start_enabled_stop_disabled_by_default(self):
        window = self._make_window()
        self.assertTrue(window.btn_start_recording.isEnabled())
        self.assertFalse(window.btn_stop_recording.isEnabled())

    # -- run active -----------------------------------------------------------

    def test_run_active_disables_start_enables_stop(self):
        window = self._make_window()
        window.apply_backend_state_snapshot(
            _make_snapshot(is_running=True, consumed=True),
        )
        self.assertFalse(window.btn_start_recording.isEnabled())
        self.assertTrue(window.btn_stop_recording.isEnabled())

    # -- session consumed after finish ----------------------------------------

    def test_consumed_session_disables_both_buttons(self):
        window = self._make_window()
        # Run started
        window.apply_backend_state_snapshot(
            _make_snapshot(is_running=True, consumed=True),
        )
        # Run finished, session consumed
        window.apply_backend_state_snapshot(
            _make_snapshot(is_running=False, consumed=True),
        )
        self.assertFalse(window.btn_start_recording.isEnabled())
        self.assertFalse(window.btn_stop_recording.isEnabled())

    def test_consumed_session_changes_start_button_text(self):
        window = self._make_window()
        window.apply_backend_state_snapshot(
            _make_snapshot(is_running=False, consumed=True),
        )
        self.assertEqual(window.btn_start_recording.text(), "Recording Done")

    def test_fresh_session_shows_start_recording_text(self):
        window = self._make_window()
        window.apply_backend_state_snapshot(
            _make_snapshot(is_running=False, consumed=False),
        )
        self.assertEqual(window.btn_start_recording.text(), "Start Recording")

    # -- snapshot without run key ---------------------------------------------

    def test_snapshot_without_run_key_enables_start(self):
        window = self._make_window()
        window.apply_backend_state_snapshot({"recording_clock": {"active": False}})
        self.assertTrue(window.btn_start_recording.isEnabled())
        self.assertFalse(window.btn_stop_recording.isEnabled())

    # -- click behaviour ------------------------------------------------------

    def test_click_start_calls_start_backend_run(self):
        window = self._make_window()
        calls: list[str] = []
        window.start_backend_run = lambda: calls.append("started")
        window.btn_start_recording.click()
        self.assertEqual(calls, ["started"])

    def test_click_stop_calls_finish_backend_run(self):
        window = self._make_window()
        window.apply_backend_state_snapshot(
            _make_snapshot(is_running=True, consumed=True),
        )
        calls: list[str] = []
        window.finish_backend_run = lambda reason="operator_stop": calls.append(reason)
        window.btn_stop_recording.click()
        self.assertEqual(calls, ["operator_stop"])

    def test_click_start_safe_without_bridge(self):
        """Clicking when start_backend_run is not injected must not crash."""
        window = self._make_window()
        if hasattr(window, "start_backend_run"):
            delattr(window, "start_backend_run")
        window.btn_start_recording.click()  # should not raise

    def test_click_start_reenables_on_exception(self):
        """If start_backend_run raises, Start Recording should re-enable."""
        window = self._make_window()

        def _raise():
            raise RuntimeError("No payload")

        window.start_backend_run = _raise
        window.btn_start_recording.click()
        self.assertTrue(window.btn_start_recording.isEnabled())

    # -- playback mode --------------------------------------------------------

    def test_playback_mode_has_no_recording_buttons(self):
        window = self._make_window(playback_mode=True)
        self.assertFalse(hasattr(window, "btn_start_recording"))
        self.assertFalse(hasattr(window, "btn_stop_recording"))

    # -- simulated respawn scenario -------------------------------------------

    def test_respawn_during_active_run_shows_correct_state(self):
        """Fresh window receives a snapshot where a run is already active
        (as happens after supervisor respawn).  Stop should be enabled."""
        window = self._make_window()
        self.assertTrue(window.btn_start_recording.isEnabled())
        self.assertFalse(window.btn_stop_recording.isEnabled())

        window.apply_backend_state_snapshot(
            _make_snapshot(is_running=True, consumed=True),
        )
        self.assertFalse(window.btn_start_recording.isEnabled())
        self.assertTrue(window.btn_stop_recording.isEnabled())

    def test_respawn_after_consumed_session_shows_locked_state(self):
        """Fresh window receives a snapshot where the session is consumed
        (run finished). Both buttons should be disabled."""
        window = self._make_window()
        window.apply_backend_state_snapshot(
            _make_snapshot(is_running=False, consumed=True),
        )
        self.assertFalse(window.btn_start_recording.isEnabled())
        self.assertFalse(window.btn_stop_recording.isEnabled())
        self.assertEqual(window.btn_start_recording.text(), "Recording Done")


if __name__ == "__main__":
    unittest.main()
