from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip

device_registry_module = import_module_or_skip("backend.device_registry")

DeviceRegistry = device_registry_module.DeviceRegistry


class _SpyBus:
    def __init__(self):
        self.riders = []
        self.calls = []

    def addRider(self, rider):
        self.riders.append(rider)
        rider._bus = self

    def send(self, packet):
        self.calls.append(("send", (packet,), {}))
        return None


class TestActualSolenoidRuntimeBusSend(unittest.TestCase):
    def test_ig_xv_24_open_touches_bus_after_registration(self):
        registry = DeviceRegistry()
        registry.load_from_settings()

        bus = _SpyBus()
        reg = registry.register_active_devices_with_bus(bus)

        self.assertIn("ig-xv-24", reg["registered_ids"])

        runtime = registry.get_runtime("ig-xv-24")
        self.assertTrue(getattr(runtime, "live_registered", False))
        self.assertIs(runtime._bus, bus)

        runtime.open()

        self.assertTrue(
            bus.calls,
            msg="runtime.open() did not call bus.send()",
        )
        self.assertEqual(bus.calls[0][0], "send")

    def test_ig_xv_24_close_touches_bus_after_registration(self):
        registry = DeviceRegistry()
        registry.load_from_settings()

        bus = _SpyBus()
        reg = registry.register_active_devices_with_bus(bus)

        self.assertIn("ig-xv-24", reg["registered_ids"])

        runtime = registry.get_runtime("ig-xv-24")
        self.assertTrue(getattr(runtime, "live_registered", False))
        self.assertIs(runtime._bus, bus)

        runtime.close()

        self.assertTrue(
            bus.calls,
            msg="runtime.close() did not call bus.send()",
        )
        self.assertEqual(bus.calls[0][0], "send")