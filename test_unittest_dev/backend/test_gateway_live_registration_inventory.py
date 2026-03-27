from __future__ import annotations

import unittest

from test_unittest_dev.helpers.fakes import FakeDeviceRegistry, FakeRuntime
from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip

service_module = import_module_or_skip("backend.service")
BackendService = service_module.BackendService


def _solenoid_meta(device_id: str, *, address: int) -> dict:
    return {
        "id": device_id,
        "name": f"Device {device_id}",
        "deviceType": "Solenoid",
        "deviceGroup": "XV",
        "deviceSystems": ["IG"],
        "address": address,
        "hasElectricalIO": True,
        "isControllable": True,
        "widgetType": "solenoid",
        "isActive": True,
    }


class TestGatewayLiveRegistrationInventory(unittest.TestCase):
    """
    Verifies backend translation from gateway registered_ids -> GUI inventory.

    If this fails, the problem is before the GUI click layer:
    backend never marked the device as live-registered.
    """

    def _make_service(self):
        service = BackendService.__new__(BackendService)
        service.device_registry = FakeDeviceRegistry(
            {
                "ig-xv-24": {
                    "meta": _solenoid_meta("ig-xv-24", address=0x70),
                    "runtime": FakeRuntime(),
                },
                "ig-xv-27": {
                    "meta": _solenoid_meta("ig-xv-27", address=0x71),
                    "runtime": FakeRuntime(),
                },
            }
        )
        return service

    def test_build_inventory_marks_only_registered_ids_as_live_registered(self):
        service = self._make_service()

        rows = service._build_device_inventory_with_live_registration(["ig-xv-24"])
        by_id = {row["id"]: row for row in rows}

        self.assertTrue(by_id["ig-xv-24"]["live_registered"])
        self.assertFalse(by_id["ig-xv-27"]["live_registered"])

    def test_build_inventory_preserves_device_id_and_address_fields(self):
        service = self._make_service()

        rows = service._build_device_inventory_with_live_registration(["ig-xv-24", "ig-xv-27"])
        by_id = {row["id"]: row for row in rows}

        self.assertEqual(by_id["ig-xv-24"]["address"], 0x70)
        self.assertEqual(by_id["ig-xv-27"]["address"], 0x71)

        # Important for diagnosing the scada fallback mismatch:
        self.assertIn("id", by_id["ig-xv-24"])
        self.assertNotIn("device_id", by_id["ig-xv-24"])