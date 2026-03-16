from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip


state_store_module = import_module_or_skip("backend.state_store")
StateStore = state_store_module.StateStore


class TestStateStoreGuiAndScript(unittest.TestCase):
    def make_store(self) -> StateStore:
        return StateStore(
            service_name="backend_service",
            backend_started_at="2026-03-15T00:00:00Z",
        )

    def test_upsert_gui_client_session_requires_connection_id(self):
        store = self.make_store()
        with self.assertRaises(ValueError):
            store.upsert_gui_client_session({"window_role": "left"})

    def test_gui_client_session_round_trip_updates_presence(self):
        store = self.make_store()
        store.set_connected_clients(1)
        store.upsert_gui_client_session(
            {
                "connection_id": "conn-1",
                "window_role": "left",
                "logical_client_id": "operator-console",
                "connected_at": "2026-03-15T00:00:00Z",
            }
        )
        snapshot = store.get_snapshot()

        self.assertEqual(snapshot["gui"]["total_windows"], 1)
        self.assertIn("left", snapshot["gui"]["window_roles"])
        self.assertIn("operator-console", snapshot["gui"]["logical_client_ids"])

        store.touch_gui_client_session(
            connection_id="conn-1",
            wall_time="2026-03-15T00:00:10Z",
            message_type="ping",
            is_ping=True,
        )
        snapshot = store.get_snapshot()
        session = snapshot["gui"]["by_connection_id"]["conn-1"]
        self.assertEqual(session["last_message_type"], "ping")
        self.assertEqual(session["last_ping_wall_time"], "2026-03-15T00:00:10Z")

        store.remove_gui_client_session(connection_id="conn-1")
        snapshot = store.get_snapshot()
        self.assertEqual(snapshot["gui"]["total_windows"], 0)

    def test_mark_script_started_and_progress(self):
        store = self.make_store()
        store.mark_script_started(
            script_id="script-1",
            name="demo-plan",
            pid=1234,
            launch_mode="plan",
            command=["plan:2 steps"],
            cwd=None,
            started_wall_time="2026-03-15T00:00:00Z",
            current_step_index=0,
            total_steps=2,
            current_step_status="starting",
            plan_steps_summary=["step 1", "step 2"],
        )

        store.update_script_progress(
            current_step_index=1,
            total_steps=2,
            current_step_name="wait for pressure",
            current_step_type="wait_state",
            current_step_status="running",
            progress_wall_time="2026-03-15T00:00:05Z",
            is_held=False,
            hold_requested=False,
        )
        snapshot = store.get_snapshot()

        self.assertTrue(snapshot["script_runner"]["is_running"])
        self.assertEqual(snapshot["script_runner"]["launch_mode"], "plan")
        self.assertEqual(snapshot["script_runner"]["current_step_index"], 1)
        self.assertEqual(snapshot["script_runner"]["current_step_type"], "wait_state")

    def test_hold_and_continue_update_script_state(self):
        store = self.make_store()
        store.mark_script_started(
            script_id="script-2",
            name="holdable",
            pid=1234,
            launch_mode="plan",
            command=["plan:1 step"],
            cwd=None,
            started_wall_time="2026-03-15T00:00:00Z",
        )

        store.mark_script_hold_requested(
            wall_time="2026-03-15T00:00:03Z",
            current_step_index=1,
            total_steps=1,
            current_step_name="sleep",
            current_step_type="sleep",
        )
        snapshot = store.get_snapshot()
        self.assertTrue(snapshot["script_runner"]["hold_requested"])
        self.assertEqual(snapshot["script_runner"]["current_step_status"], "hold_requested")

        store.mark_script_held(
            wall_time="2026-03-15T00:00:04Z",
            current_step_index=1,
            total_steps=1,
            current_step_name="sleep",
            current_step_type="sleep",
        )
        snapshot = store.get_snapshot()
        self.assertTrue(snapshot["script_runner"]["is_held"])
        self.assertEqual(snapshot["script_runner"]["current_step_status"], "held")

        store.mark_script_continued(
            wall_time="2026-03-15T00:00:05Z",
            current_step_index=1,
            total_steps=1,
            current_step_name="sleep",
            current_step_type="sleep",
        )
        snapshot = store.get_snapshot()
        self.assertFalse(snapshot["script_runner"]["is_held"])
        self.assertFalse(snapshot["script_runner"]["hold_requested"])
        self.assertEqual(snapshot["script_runner"]["current_step_status"], "running")

    def test_clear_script_running_state_removes_transient_fields(self):
        store = self.make_store()
        store.mark_script_started(
            script_id="script-3",
            name="cleanup-demo",
            pid=1234,
            launch_mode="plan",
            command=["plan:1 step"],
            cwd="/tmp",
            started_wall_time="2026-03-15T00:00:00Z",
            current_step_index=1,
            total_steps=1,
            current_step_name="note",
            current_step_type="note",
            current_step_status="running",
        )
        store.clear_script_running_state()
        snapshot = store.get_snapshot()

        self.assertFalse(snapshot["script_runner"]["is_running"])
        self.assertIsNone(snapshot["script_runner"]["script_id"])
        self.assertEqual(snapshot["script_runner"]["command"], [])
        self.assertIsNone(snapshot["script_runner"]["current_step_name"])
