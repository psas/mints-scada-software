from __future__ import annotations

import unittest
from types import MethodType

from test_unittest_dev.helpers.repo_test_tools import (
    get_qapplication,
    import_module_or_skip,
    temp_project_root,
    write_json,
)


checklist_module = import_module_or_skip("gui.checklist_window")
ChecklistWindow = checklist_module.ChecklistWindow


class TestChecklistWindowPlaybackSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = get_qapplication()

    def make_window(self):
        window = ChecklistWindow("/tmp/missing-serial", backend_socket_path="/tmp/does-not-exist.sock", auto_refresh_ms=60_000)
        self.addCleanup(window.close)
        if hasattr(window, "_check_refresh_timer"):
            window._check_refresh_timer.stop()
        return window

    def populate_run(self, root, run_id: str):
        run_dir = root / "ignitionhistory" / run_id
        (run_dir / "snapshots").mkdir(parents=True, exist_ok=True)
        write_json(
            run_dir / "metadata.json",
            {
                "run_id": run_id,
                "status": "completed",
                "mode": "live",
                "test_name": "Playback Test",
                "operator": "Eric",
                "start_wall_time": "2026-03-15T00:00:00Z",
                "end_wall_time": "2026-03-15T00:01:00Z",
            },
        )
        write_json(
            run_dir / "integrity_report.json",
            {
                "overall_status": "ok",
                "badge": "green",
                "summary_message": "All data matches natively",
            },
        )
        (run_dir / "merged.jsonl").write_text("", encoding="utf-8")

    def test_playback_continue_requires_explicit_selection(self):
        with temp_project_root() as root:
            self.populate_run(root, "run_a")
            window = self.make_window()
            window._project_root = MethodType(lambda self: root, window)

            window.show_playback_selection()

            self.assertEqual(window.test_list.count(), 1)
            self.assertFalse(window.playback_continue_button.isEnabled())

            item = window.test_list.item(0)
            window.test_list.setCurrentItem(item)
            window.on_playback_item_changed(item, None)

            self.assertTrue(window.playback_continue_button.isEnabled())
            # Simply selecting an item should not accept the dialog yet.
            self.assertIsNone(window.selected_test)

            window.on_test_selected()
            self.assertEqual(window.selected_test, "run_a")
            self.assertTrue(window.playback_mode)

    def test_no_runs_available_shows_placeholder(self):
        with temp_project_root() as root:
            window = self.make_window()
            window._project_root = MethodType(lambda self: root, window)

            window.show_playback_selection()

            self.assertEqual(window.test_list.count(), 1)
            self.assertIn("No playback runs available", window.test_list.item(0).text())
            self.assertFalse(window.playback_continue_button.isEnabled())
