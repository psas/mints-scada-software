from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from test_unittest_dev.helpers.repo_test_tools import (
    import_module_or_skip,
    temp_project_root,
    write_json,
)


playback_catalog = import_module_or_skip("gui.playback_catalog")


class TestPlaybackCatalog(unittest.TestCase):
    def make_run(self, root, run_id: str, *, with_integrity_report: bool = False):
        run_dir = root / "ignitionhistory" / run_id
        (run_dir / "snapshots").mkdir(parents=True, exist_ok=True)
        write_json(
            run_dir / "metadata.json",
            {
                "run_id": run_id,
                "status": "completed",
                "mode": "live",
                "test_name": f"Test {run_id}",
                "operator": "Eric",
                "profile_name": "baseline",
                "start_wall_time": "2026-03-15T00:00:00Z",
                "end_wall_time": "2026-03-15T00:05:00Z",
                "notes": "Test notes",
            },
        )
        (run_dir / "merged.jsonl").write_text("", encoding="utf-8")
        if with_integrity_report:
            write_json(
                run_dir / playback_catalog.INTEGRITY_REPORT_FILENAME,
                {
                    "overall_status": "ok",
                    "badge": "green",
                    "summary_message": "All data matches natively",
                },
            )
        return run_dir

    def test_discovers_run_and_reads_saved_integrity_report(self):
        with temp_project_root() as root:
            self.make_run(root, "run_saved_report", with_integrity_report=True)

            runs = playback_catalog.discover_playback_runs(root, include_integrity=True)

            self.assertEqual(len(runs), 1)
            summary = runs[0]
            self.assertEqual(summary.run_id, "run_saved_report")
            self.assertEqual(summary.integrity_status, "ok")
            self.assertEqual(summary.integrity_badge, "green")
            self.assertIn("archive=ok", summary.display_subtitle)

    def test_discovers_run_and_falls_back_to_scan_when_report_missing(self):
        with temp_project_root() as root:
            self.make_run(root, "run_scan_fallback", with_integrity_report=False)

            with patch(
                "gui.playback_catalog._scan_integrity_report",
                return_value={
                    "overall_status": "partial",
                    "badge": "yellow",
                    "summary_message": "Missing from rawbak",
                },
            ):
                runs = playback_catalog.discover_playback_runs(root, include_integrity=True)

            self.assertEqual(len(runs), 1)
            summary = runs[0]
            self.assertEqual(summary.integrity_status, "partial")
            self.assertEqual(summary.integrity_badge, "yellow")
            self.assertIn("Missing from rawbak", summary.tooltip_text)

    def test_sort_order_prefers_newer_runs(self):
        with temp_project_root() as root:
            self.make_run(root, "run_old", with_integrity_report=True)
            write_json(
                root / "ignitionhistory" / "run_old" / "metadata.json",
                {
                    "run_id": "run_old",
                    "status": "completed",
                    "mode": "live",
                    "test_name": "Old",
                    "operator": "Eric",
                    "start_wall_time": "2026-03-15T00:00:00Z",
                    "end_wall_time": "2026-03-15T00:01:00Z",
                },
            )
            self.make_run(root, "run_new", with_integrity_report=True)
            write_json(
                root / "ignitionhistory" / "run_new" / "metadata.json",
                {
                    "run_id": "run_new",
                    "status": "completed",
                    "mode": "live",
                    "test_name": "New",
                    "operator": "Eric",
                    "start_wall_time": "2026-03-16T00:00:00Z",
                    "end_wall_time": "2026-03-16T00:01:00Z",
                },
            )

            runs = playback_catalog.discover_playback_runs(root, include_integrity=False)
            self.assertEqual([run.run_id for run in runs], ["run_new", "run_old"])
