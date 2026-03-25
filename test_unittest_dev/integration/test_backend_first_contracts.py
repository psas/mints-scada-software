from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip


state_store_module = import_module_or_skip("backend.state_store")
playback_catalog_module = import_module_or_skip("gui.playback_catalog")
script_runner_module = import_module_or_skip("backend.script_runner")

StateStore = state_store_module.StateStore
ScriptRunner = script_runner_module.ScriptRunner


class TestBackendFirstContracts(unittest.TestCase):
    def test_state_store_exposes_backend_owned_live_clocks(self):
        store = StateStore(
            service_name="backend_service",
            backend_started_at="2026-03-15T00:00:00Z",
        )
        snapshot = store.get_snapshot()

        self.assertIn("mission_clock", snapshot)
        self.assertIn("recording_clock", snapshot)
        self.assertIn("playback_clock", snapshot)

    def test_playback_catalog_summary_exposes_integrity_fields(self):
        summary = playback_catalog_module.PlaybackRunSummary(
            run_id="run_1",
            run_dir=__import__("pathlib").Path("/tmp/run_1"),
            metadata_path=__import__("pathlib").Path("/tmp/run_1/metadata.json"),
            complete_path=__import__("pathlib").Path("/tmp/run_1/complete.json"),
            snapshots_dir=__import__("pathlib").Path("/tmp/run_1/snapshots"),
            start_wall_time="2026-03-15T00:00:00Z",
            end_wall_time="2026-03-15T00:01:00Z",
            status="completed",
            mode="live",
            test_name="Demo",
            operator="Eric",
            profile_name="baseline",
            notes="note",
            snapshot_count=2,
            has_merged=True,
            integrity_status="ok",
            integrity_badge="green",
            integrity_summary_message="All data matches natively",
            integrity_report_path=None,
            integrity_report={"overall_status": "ok"},
        )

        self.assertIn("archive=ok", summary.display_subtitle)
        self.assertIn("Integrity status: ok", summary.tooltip_text)

    def test_script_runner_status_snapshot_exposes_hold_capability_flag(self):
        runner = ScriptRunner()
        snapshot = runner.get_status_snapshot()

        self.assertIn("supports_hold_continue", snapshot)
        self.assertFalse(snapshot["supports_hold_continue"])
