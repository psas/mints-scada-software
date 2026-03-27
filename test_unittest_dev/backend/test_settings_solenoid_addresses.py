from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip

settings = import_module_or_skip("settings")


def _devices_by_id() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for raw in settings.devices:
        meta = settings.normalize_device_desc(dict(raw))
        rows[meta["id"]] = meta
    return rows


class TestSettingsSolenoidAddresses(unittest.TestCase):
    """
    Sanity-check the exact local settings.py that unittest is importing.

    If this fails, stop there first:
    you are either not running the edited local tree,
    or the local settings entry was not saved as expected.
    """

    def test_ig_xv_addresses_match_expected_local_values(self):
        devices = _devices_by_id()

        self.assertIn("ig-xv-24", devices)
        self.assertIn("ig-xv-27", devices)

        self.assertEqual(devices["ig-xv-24"]["address"], 0x70)
        self.assertEqual(devices["ig-xv-27"]["address"], 0x71)

    def test_ig_xv_entries_are_controllable_live_solenoids(self):
        devices = _devices_by_id()

        xv24 = devices["ig-xv-24"]
        xv27 = devices["ig-xv-27"]

        for row in (xv24, xv27):
            self.assertEqual(row["deviceType"], "Solenoid")
            self.assertEqual(row["deviceGroup"], "XV")
            self.assertEqual(row["widgetType"], "solenoid")
            self.assertTrue(row["hasElectricalIO"])
            self.assertTrue(row["isControllable"])
            self.assertTrue(row["isActive"])