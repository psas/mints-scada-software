from __future__ import annotations

import tempfile
import unittest
from types import MethodType

from test_unittest_dev.helpers.repo_test_tools import get_qapplication, import_module_or_skip


checklist_module = import_module_or_skip("gui.checklist_window")
ChecklistWindow = checklist_module.ChecklistWindow


class TestChecklistWindowLiveSetup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = get_qapplication()

    def make_window(self):
        serial = tempfile.NamedTemporaryFile(delete=False)
        serial.close()
        window = ChecklistWindow(serial.name, backend_socket_path="/tmp/does-not-exist.sock", auto_refresh_ms=60_000)
        self.addCleanup(window.close)
        if hasattr(window, "_check_refresh_timer"):
            window._check_refresh_timer.stop()
        return window

    def test_live_continue_requires_test_name_and_operator(self):
        window = self.make_window()
        window.show_live_setup()

        self.assertFalse(window.live_continue_button.isEnabled())

        window.test_name_input.setText("LOX proof test")
        window._update_live_continue_state()
        self.assertFalse(window.live_continue_button.isEnabled())

        window.operator_input.setText("Eric")
        window._update_live_continue_state()
        self.assertTrue(window.live_continue_button.isEnabled())
        self.assertIn("ready", window.live_setup_status.text().lower())

    def test_on_live_selected_requires_test_name(self):
        window = self.make_window()
        window.show_live_setup()

        window.operator_input.setText("Eric")
        window.on_live_selected()

        self.assertIsNone(window.live_run_metadata)
        self.assertIn("required", window.live_setup_status.text().lower())

    def test_on_live_selected_accepts_and_collects_metadata(self):
        window = self.make_window()
        window.show_live_setup()

        window.test_name_input.setText("Igniter checkout")
        window.operator_input.setText("Eric")
        window.profile_input.setText("baseline")
        window.notes_input.setPlainText("operator note")

        window.on_live_selected()

        self.assertEqual(window.live_run_metadata["test_name"], "Igniter checkout")
        self.assertEqual(window.live_run_metadata["operator"], "Eric")
        self.assertEqual(window.live_run_metadata["profile_name"], "baseline")
        self.assertEqual(window.live_run_metadata["notes"], "operator note")
        self.assertFalse(window.playback_mode)

    def test_run_checks_backend_ready_unlocks_live(self):
        window = self.make_window()

        def fake_probe(self, *, timeout_s=0.75):
            return {
                "reachable": True,
                "message": "Backend service responded",
                "snapshot": {
                    "bus": {"connected": True, "reconnecting": False, "sender": "socketcan", "bitrate": 500000},
                    "registry": {"total_devices": 3, "load_error_count": 0},
                },
            }

        window._probe_backend_live_state = MethodType(fake_probe, window)
        window.run_checks()

        self.assertTrue(window.all_passed)
        self.assertTrue(window.continue_button.isEnabled())
        self.assertIn("All checks passed", window.status_message.text())
