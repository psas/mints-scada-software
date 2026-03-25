from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_unittest_dev.helpers.fakes import FakeHistoryManager
from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip


state_store_module = import_module_or_skip("backend.state_store")
run_controller_module = import_module_or_skip("backend.run_controller")

StateStore = state_store_module.StateStore
RunController = run_controller_module.RunController


class TestRunControllerLifecycle(unittest.TestCase):
    def make_controller(self):
        tempdir = TemporaryDirectory()
        history = FakeHistoryManager(snapshot_dir=Path(tempdir.name) / "snapshots")
        store = StateStore(
            service_name="backend_service",
            backend_started_at="2026-03-15T00:00:00Z",
        )
        controller = RunController(history_manager=history, state_store=store)
        return tempdir, history, store, controller

    def test_start_run_marks_state_and_writes_initial_snapshot(self):
        tempdir, history, store, controller = self.make_controller()
        self.addCleanup(tempdir.cleanup)

        result = controller.start_run(
            test_name="Igniter dry fire",
            mode="live",
            operator="Eric",
            profile_name="baseline",
            notes="initial pass",
        )

        self.assertEqual(result["status"], "running")
        self.assertTrue(result["archive_initialized"])
        self.assertEqual(history.current_run.run_id, result["run_id"])
        self.assertEqual(len(history.raw_events), 1)
        self.assertEqual(history.raw_events[0][0], "system_event")
        self.assertEqual(history.raw_events[0][1]["event_type"], "run_archive_initialized")
        self.assertEqual(len(history.structured_events), 1)
        self.assertEqual(len(history.snapshots), 1)

        snapshot = store.get_snapshot()
        self.assertTrue(snapshot["run"]["is_running"])
        self.assertEqual(snapshot["run"]["test_name"], "Igniter dry fire")

    def test_finish_run_marks_state_and_records_integrity_summary(self):
        tempdir, history, store, controller = self.make_controller()
        self.addCleanup(tempdir.cleanup)

        controller.start_run(test_name="Main valve test", mode="live", operator="Eric")

        with patch(
            "backend.run_controller.scan_and_write_run_integrity",
            return_value=(
                {
                    "overall_status": "ok",
                    "badge": "green",
                    "summary_message": "All data matches natively",
                },
                Path(tempdir.name) / "integrity_report.json",
            ),
        ):
            result = controller.finish_run(reason="operator_stop")

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["archive_finalized"])
        self.assertEqual(result["integrity_status"], "ok")
        self.assertEqual(result["integrity_badge"], "green")
        self.assertIn("All data matches", result["integrity_summary_message"])

        snapshot = store.get_snapshot()
        self.assertFalse(snapshot["run"]["is_running"])
        self.assertEqual(snapshot["run"]["status"], "completed")
        self.assertEqual(len(history.snapshots), 2)
        self.assertEqual(history.raw_events[-1][1]["event_type"], "run_archive_finalizing")

    def test_finish_run_reports_integrity_scan_error_without_failing_shutdown(self):
        tempdir, history, store, controller = self.make_controller()
        self.addCleanup(tempdir.cleanup)

        controller.start_run(test_name="Pressure hold", mode="live", operator="Eric")

        with patch(
            "backend.run_controller.scan_and_write_run_integrity",
            side_effect=RuntimeError("integrity exploded"),
        ):
            result = controller.finish_run(reason="operator_stop")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["integrity_status"], "unknown")
        self.assertEqual(result["integrity_badge"], "red")
        self.assertIn("integrity exploded", result["integrity_summary_message"])
        self.assertEqual(result["integrity_scan_error"], "integrity exploded")

    def test_finish_run_without_active_run_raises(self):
        tempdir, history, store, controller = self.make_controller()
        self.addCleanup(tempdir.cleanup)

        with self.assertRaises(RuntimeError):
            controller.finish_run(reason="operator_stop")
