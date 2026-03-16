from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip


state_store_module = import_module_or_skip("backend.state_store")
StateStore = state_store_module.StateStore


class TestStateStoreHealthAndBackendStatus(unittest.TestCase):
    def make_store(self) -> StateStore:
        return StateStore(
            service_name="backend_service",
            backend_started_at="2026-03-15T00:00:00Z",
        )

    def test_set_bus_connection_state_appears_in_snapshot(self):
        store = self.make_store()
        store.set_bus_connection_state(
            connected=True,
            reconnecting=False,
            sender="socketcan",
            bitrate=500000,
            registered_ids=["xv-1"],
            skipped_ids=[],
            wall_time="2026-03-15T00:00:00Z",
        )
        snapshot = store.get_snapshot()

        self.assertTrue(snapshot["bus"]["connected"])
        self.assertEqual(snapshot["bus"]["sender"], "socketcan")
        self.assertEqual(snapshot["bus"]["bitrate"], 500000)
        self.assertEqual(snapshot["bus"]["registered_ids"], ["xv-1"])

    def test_set_health_snapshot_is_reflected_in_backend_status(self):
        store = self.make_store()
        store.set_health_snapshot(
            sampled_at="2026-03-15T00:01:00Z",
            overall_status="warning",
            active_warnings=["raw writer lagging", "gui client stale"],
            writers={"raw": {"status": "lagging"}},
            bus={"status": "connected"},
            script={"status": "idle"},
            gui={"status": "warning", "warning_count": 1},
        )
        status = store.get_backend_status()

        self.assertEqual(status["health_summary"]["overall_status"], "warning")
        self.assertEqual(status["health_summary"]["active_warning_count"], 2)
        self.assertEqual(status["health_summary"]["gui_status"], "warning")
