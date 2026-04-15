from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip


state_store_module = import_module_or_skip("backend.state_store")
StateStore = state_store_module.StateStore


class TestStateStoreAbort(unittest.TestCase):
    """Verify backend-authoritative abort latch state in StateStore."""

    def make_store(self) -> StateStore:
        return StateStore(
            service_name="backend_service",
            backend_started_at="2026-03-15T00:00:00Z",
        )

    def test_abort_latch_default_false(self):
        store = self.make_store()
        snapshot = store.get_snapshot()
        self.assertIn("abort", snapshot)
        self.assertFalse(snapshot["abort"]["abort_latched"])
        self.assertIsNone(snapshot["abort"]["latched_at"])
        self.assertIsNone(snapshot["abort"]["latched_by"])
        self.assertIsNone(snapshot["abort"]["latched_request_id"])

    def test_mark_abort_latched_sets_fields(self):
        store = self.make_store()
        store.mark_abort_latched(
            latched_by="gui",
            request_id="req-abc",
            wall_time="2026-03-15T00:01:00Z",
        )
        snapshot = store.get_snapshot()
        abort = snapshot["abort"]
        self.assertTrue(abort["abort_latched"])
        self.assertEqual(abort["latched_at"], "2026-03-15T00:01:00Z")
        self.assertEqual(abort["latched_by"], "gui")
        self.assertEqual(abort["latched_request_id"], "req-abc")

    def test_clear_abort_latch_clears_fields(self):
        store = self.make_store()
        store.mark_abort_latched(
            latched_by="gui",
            request_id="req-abc",
            wall_time="2026-03-15T00:01:00Z",
        )
        store.clear_abort_latch(wall_time="2026-03-15T00:02:00Z")
        snapshot = store.get_snapshot()
        abort = snapshot["abort"]
        self.assertFalse(abort["abort_latched"])
        self.assertIsNone(abort["latched_at"])
        self.assertIsNone(abort["latched_by"])
        self.assertIsNone(abort["latched_request_id"])

    def test_abort_state_in_snapshot(self):
        """Verify the abort section appears in the full snapshot dict."""
        store = self.make_store()
        snapshot = store.get_snapshot()
        self.assertIn("abort", snapshot)
        self.assertIsInstance(snapshot["abort"], dict)

    def test_mark_abort_latched_without_optional_fields(self):
        store = self.make_store()
        store.mark_abort_latched()
        snapshot = store.get_snapshot()
        self.assertTrue(snapshot["abort"]["abort_latched"])
        # latched_at is auto-filled when not supplied
        self.assertIsNotNone(snapshot["abort"]["latched_at"])

    def test_clear_abort_latch_is_idempotent(self):
        store = self.make_store()
        # Clear without ever latching — should not error
        store.clear_abort_latch()
        snapshot = store.get_snapshot()
        self.assertFalse(snapshot["abort"]["abort_latched"])

    def test_double_latch_updates_fields(self):
        store = self.make_store()
        store.mark_abort_latched(
            latched_by="gui",
            request_id="req-1",
            wall_time="2026-03-15T00:01:00Z",
        )
        store.mark_abort_latched(
            latched_by="script",
            request_id="req-2",
            wall_time="2026-03-15T00:02:00Z",
        )
        snapshot = store.get_snapshot()
        abort = snapshot["abort"]
        self.assertTrue(abort["abort_latched"])
        self.assertEqual(abort["latched_by"], "script")
        self.assertEqual(abort["latched_request_id"], "req-2")

    def test_latch_clear_latch_cycle(self):
        store = self.make_store()
        store.mark_abort_latched(latched_by="gui", request_id="req-1")
        store.clear_abort_latch()
        store.mark_abort_latched(latched_by="gui", request_id="req-2")
        snapshot = store.get_snapshot()
        self.assertTrue(snapshot["abort"]["abort_latched"])
        self.assertEqual(snapshot["abort"]["latched_request_id"], "req-2")


if __name__ == "__main__":
    unittest.main()
