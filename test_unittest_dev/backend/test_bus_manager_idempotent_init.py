from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip


bus_manager_module = import_module_or_skip("backend.bus_manager")
BusInitResult = bus_manager_module.BusInitResult
BusManager = bus_manager_module.BusManager


class TestBusManagerIdempotentInit(unittest.TestCase):
    """Verify that calling initialize_live_hardware when already running
    returns a success result with ``already_running=True`` instead of raising.

    These tests exercise the BusManager's idempotency guard directly without
    requiring real CAN hardware.  We manually set internal state to simulate
    the "already running" condition.
    """

    def _make_running_manager(self) -> BusManager:
        """Create a BusManager that appears to be running with a cached init result."""
        manager = BusManager(
            sender="/dev/null",
            bitrate=1000000,
            auto_reconnect=False,
        )
        # Simulate that initialize_live_hardware was already called successfully
        # by setting the internal state the real method would set.
        manager._entered = True
        manager._bus = object()  # non-None sentinel
        manager._last_init_result = BusInitResult(
            sender="/dev/null",
            bitrate=1000000,
            registered_ids=["ig-xv-24", "ipa-xv-23"],
            skipped_ids=["tt-1"],
            registered_count=2,
            skipped_count=1,
        )
        return manager

    def test_already_running_returns_result_not_raises(self):
        manager = self._make_running_manager()
        self.assertTrue(manager.is_running)

        # Should NOT raise RuntimeError
        result = manager.initialize_live_hardware(registry=None)

        self.assertIsInstance(result, BusInitResult)
        self.assertTrue(result.already_running)
        self.assertEqual(result.sender, "/dev/null")
        self.assertEqual(result.bitrate, 1000000)

    def test_already_running_preserves_cached_device_ids(self):
        manager = self._make_running_manager()
        result = manager.initialize_live_hardware(registry=None)

        self.assertEqual(result.registered_ids, ["ig-xv-24", "ipa-xv-23"])
        self.assertEqual(result.skipped_ids, ["tt-1"])
        self.assertEqual(result.registered_count, 2)
        self.assertEqual(result.skipped_count, 1)

    def test_already_running_returns_independent_list_copies(self):
        manager = self._make_running_manager()
        result = manager.initialize_live_hardware(registry=None)

        # Verify the returned lists are copies, not references to cached state.
        result.registered_ids.append("mutated")
        cached = manager.last_init_result
        self.assertNotIn("mutated", cached.registered_ids)

    def test_already_running_without_cached_result_still_returns(self):
        manager = self._make_running_manager()
        manager._last_init_result = None

        result = manager.initialize_live_hardware(registry=None)

        self.assertTrue(result.already_running)
        self.assertEqual(result.registered_ids, [])
        self.assertEqual(result.registered_count, 0)

    def test_fresh_init_result_has_already_running_false(self):
        result = BusInitResult(
            sender="/dev/null",
            bitrate=1000000,
            registered_ids=[],
            skipped_ids=[],
            registered_count=0,
            skipped_count=0,
        )
        self.assertFalse(result.already_running)


if __name__ == "__main__":
    unittest.main()
