from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip

settings = import_module_or_skip("settings")
device_registry_module = import_module_or_skip("backend.device_registry")

DeviceRegistry = device_registry_module.DeviceRegistry


class _RecordingBus:
    def __init__(self):
        self.riders = []

    def addRider(self, rider):
        self.riders.append(rider)


def _normalized_by_id() -> dict[str, dict]:
    rows = {}
    for raw in settings.devices:
        meta = settings.normalize_device_desc(dict(raw))
        rows[meta["id"]] = meta
    return rows


class TestLiveRegistrationActualSettings(unittest.TestCase):
    """
    This is the first test that exercises the actual local settings.py
    together with the actual DeviceRegistry registration path.
    """

    def test_ig_solenoids_have_no_load_errors_and_exist_in_registry(self):
        registry = DeviceRegistry()
        registry.load_from_settings()

        load_errors = registry.get_load_errors()
        self.assertEqual(load_errors, [])

        for device_id in ("ig-xv-24", "ig-xv-27"):
            meta = registry.get_meta(device_id)
            self.assertEqual(meta["id"], device_id)
            self.assertTrue(meta["isActive"])
            self.assertTrue(meta["hasElectricalIO"])
            self.assertTrue(meta["isControllable"])

    def test_ig_solenoids_register_on_bus_from_actual_local_settings(self):
        registry = DeviceRegistry()
        registry.load_from_settings()

        bus = _RecordingBus()
        result = registry.register_active_devices_with_bus(bus)

        registered_ids = set(result["registered_ids"])
        skipped_ids = set(result["skipped_ids"])

        self.assertIn("ig-xv-24", registered_ids)
        self.assertIn("ig-xv-27", registered_ids)

        self.assertNotIn("ig-xv-24", skipped_ids)
        self.assertNotIn("ig-xv-27", skipped_ids)

    def test_ig_addresses_are_not_shared_by_other_active_electrical_devices(self):
        by_id = _normalized_by_id()
        target_addresses = {
            "ig-xv-24": by_id["ig-xv-24"]["address"],
            "ig-xv-27": by_id["ig-xv-27"]["address"],
        }

        collisions: dict[str, list[str]] = {"ig-xv-24": [], "ig-xv-27": []}

        for other_id, meta in by_id.items():
            if other_id in target_addresses:
                continue
            if not meta["isActive"]:
                continue
            if not meta["hasElectricalIO"]:
                continue

            for target_id, target_address in target_addresses.items():
                if meta["address"] == target_address:
                    collisions[target_id].append(other_id)

        self.assertEqual(
            collisions["ig-xv-24"],
            [],
            msg=f"ig-xv-24 address {target_addresses['ig-xv-24']:#04x} collides with {collisions['ig-xv-24']}",
        )
        self.assertEqual(
            collisions["ig-xv-27"],
            [],
            msg=f"ig-xv-27 address {target_addresses['ig-xv-27']:#04x} collides with {collisions['ig-xv-27']}",
        )