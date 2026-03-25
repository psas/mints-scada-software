from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip


state_store_module = import_module_or_skip("backend.state_store")
StateStore = state_store_module.StateStore


class TestStateStoreRunAndClocks(unittest.TestCase):
    def make_store(self) -> StateStore:
        return StateStore(
            service_name="backend_service",
            backend_started_at="2026-03-15T00:00:00Z",
        )

    def test_initial_snapshot_contains_major_sections(self):
        store = self.make_store()
        snapshot = store.get_snapshot()

        for key in (
            "run",
            "bus",
            "device_registry",
            "device_runtime",
            "recording_clock",
            "mission_clock",
            "playback_clock",
            "gui",
            "script_runner",
            "health",
            "archive",
        ):
            self.assertIn(key, snapshot, f"Missing top-level snapshot key: {key}")

    def test_mark_run_started_live_enables_recording_clock(self):
        store = self.make_store()

        store.mark_run_started(
            run_id="run_live_001",
            mode="live",
            test_name="Hotfire Practice",
            operator="Eric",
            profile_name="baseline",
            started_wall_time="2026-03-15T01:02:03Z",
            notes="live run",
            metadata={"phase": "dev"},
        )
        snapshot = store.get_snapshot()

        self.assertEqual(snapshot["run"]["active_run_id"], "run_live_001")
        self.assertTrue(snapshot["run"]["is_running"])
        self.assertEqual(snapshot["run"]["mode"], "live")
        self.assertEqual(snapshot["run"]["status"], "running")
        self.assertEqual(snapshot["run"]["test_name"], "Hotfire Practice")
        self.assertTrue(snapshot["recording_clock"]["active"])
        self.assertEqual(snapshot["recording_clock"]["status"], "recording")
        self.assertIn("Recording:", snapshot["recording_clock"]["display_text"])
        self.assertFalse(snapshot["playback_clock"]["active"])

    def test_mark_run_started_playback_enables_playback_clock(self):
        store = self.make_store()

        store.mark_run_started(
            run_id="run_playback_001",
            mode="playback",
            test_name="Replay",
            operator="Eric",
            profile_name="replay-profile",
            started_wall_time="2026-03-15T02:00:00Z",
            notes=None,
            metadata=None,
        )
        snapshot = store.get_snapshot()

        self.assertFalse(snapshot["recording_clock"]["active"])
        self.assertEqual(snapshot["recording_clock"]["display_text"], "Not Recording")
        self.assertTrue(snapshot["playback_clock"]["active"])
        self.assertEqual(snapshot["playback_clock"]["source_run_id"], "run_playback_001")
        self.assertEqual(snapshot["playback_clock"]["status"], "ready")

    def test_mark_run_finished_sets_completed_state(self):
        store = self.make_store()
        store.mark_run_started(
            run_id="run_live_002",
            mode="live",
            test_name="Shutdown test",
            operator="Operator A",
            profile_name=None,
            started_wall_time="2026-03-15T00:00:00Z",
        )

        store.mark_run_finished(
            run_id="run_live_002",
            finished_wall_time="2026-03-15T00:02:30Z",
            reason="operator_stop",
        )
        snapshot = store.get_snapshot()

        self.assertFalse(snapshot["run"]["is_running"])
        self.assertEqual(snapshot["run"]["status"], "completed")
        self.assertEqual(snapshot["run"]["last_finish_reason"], "operator_stop")
        self.assertEqual(snapshot["recording_clock"]["status"], "stopped")
        self.assertIn("Recording:", snapshot["recording_clock"]["display_text"])

    def test_set_mission_clock_updates_backend_status(self):
        store = self.make_store()
        store.set_mission_clock(seconds=12.5, state="held", label="T+")

        status = store.get_backend_status()
        self.assertEqual(status["mission_clock"]["state"], "held")
        self.assertAlmostEqual(status["mission_clock"]["seconds"], 12.5)
        self.assertEqual(status["mission_clock"]["label"], "T+")

    def test_set_playback_clock_updates_backend_status(self):
        store = self.make_store()
        store.set_playback_clock(
            source_run_id="recording_123",
            total_duration_seconds=305.0,
            position_seconds=22.0,
            status="playing",
            wall_time="2026-03-15T00:10:00Z",
        )

        status = store.get_backend_status()
        self.assertTrue(status["playback_clock"]["active"])
        self.assertEqual(status["playback_clock"]["status"], "playing")
        self.assertEqual(status["playback_clock"]["position_seconds"], 22.0)
        self.assertEqual(status["playback_clock"]["total_duration_seconds"], 305.0)

    def test_backend_status_includes_last_command_summary(self):
        store = self.make_store()
        status = store.get_backend_status()

        self.assertIn("last_command", status)
        self.assertIsInstance(status["last_command"], dict)
