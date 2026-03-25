from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_unittest_dev.helpers.fakes import FakeHistoryManager
from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip, write_json


state_store_module = import_module_or_skip("backend.state_store")
run_controller_module = import_module_or_skip("backend.run_controller")
playback_catalog = import_module_or_skip("gui.playback_catalog")

StateStore = state_store_module.StateStore
RunController = run_controller_module.RunController


class TestRunControllerAndCatalogFlow(unittest.TestCase):
    def test_finished_run_result_has_integrity_fields_expected_by_playback_ui(self):
        with TemporaryDirectory() as tmp:
            history = FakeHistoryManager(snapshot_dir=Path(tmp) / "snapshots")
            store = StateStore(
                service_name="backend_service",
                backend_started_at="2026-03-15T00:00:00Z",
            )
            controller = RunController(history_manager=history, state_store=store)

            controller.start_run(test_name="Integrated flow", mode="live", operator="Eric")

            with patch(
                "backend.run_controller.scan_and_write_run_integrity",
                return_value=(
                    {
                        "overall_status": "ok",
                        "badge": "green",
                        "summary_message": "All data matches natively",
                    },
                    Path(tmp) / "integrity_report.json",
                ),
            ):
                result = controller.finish_run(reason="operator_stop")

            self.assertIn("integrity_status", result)
            self.assertIn("integrity_badge", result)
            self.assertIn("integrity_summary_message", result)
            self.assertEqual(result["integrity_status"], "ok")

    def test_playback_catalog_reads_metadata_and_integrity_artifact_together(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "ignitionhistory" / "run_catalog"
            (run_dir / "snapshots").mkdir(parents=True, exist_ok=True)

            write_json(
                run_dir / "metadata.json",
                {
                    "run_id": "run_catalog",
                    "status": "completed",
                    "mode": "live",
                    "test_name": "Catalog Integration",
                    "operator": "Eric",
                    "start_wall_time": "2026-03-15T00:00:00Z",
                    "end_wall_time": "2026-03-15T00:03:00Z",
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

            runs = playback_catalog.discover_playback_runs(root, include_integrity=True)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0].run_id, "run_catalog")
            self.assertEqual(runs[0].integrity_badge, "green")
