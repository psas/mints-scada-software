from __future__ import annotations

import unittest

from test_unittest_dev.helpers.fakes import FakeBusManager, FakeDeviceRegistry, FakeRuntime
from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip

command_router_module = import_module_or_skip("backend.command_router")
CommandRouter = command_router_module.CommandRouter


def _snapshot() -> dict:
    return {
        "run": {"mode": "live", "status": "running"},
        "bus": {"connected": True, "reconnecting": False},
        "script_runner": {"is_held": False},
        "device_runtime": {"by_id": {}},
    }


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


class TestCommandRouterXVPositivePath(unittest.TestCase):
    """
    Distinguishes a real runtime dispatch from a mock-only accept.

    If the mock_only case passes but the real dispatch case fails,
    the blockage is in backend dispatch / runtime adapter land.
    """

    def _make_router(self):
        runtime = FakeRuntime()
        registry = FakeDeviceRegistry(
            {
                "ig-xv-24": {
                    "meta": _solenoid_meta("ig-xv-24", address=0x70),
                    "runtime": runtime,
                }
            }
        )
        router = CommandRouter(
            device_registry=registry,
            bus_manager=FakeBusManager(),
            state_snapshot_getter=_snapshot,
        )
        return router, runtime

    def test_open_dispatches_to_runtime_when_not_mock(self):
        router, runtime = self._make_router()

        result = router.route_command(
            {
                "command_name": "open",
                "device_id": "ig-xv-24",
                "mock_only": False,
            }
        )

        self.assertTrue(result.success)
        self.assertEqual(getattr(result, "dispatched_via", None), "runtime_method")
        self.assertEqual(runtime.calls, [("open", (), {})])

    def test_close_dispatches_to_runtime_when_not_mock(self):
        router, runtime = self._make_router()

        result = router.route_command(
            {
                "command_name": "close",
                "device_id": "ig-xv-24",
                "mock_only": False,
            }
        )

        self.assertTrue(result.success)
        self.assertEqual(getattr(result, "dispatched_via", None), "runtime_method")
        self.assertEqual(runtime.calls, [("close", (), {})])

    def test_mock_only_accepts_without_touching_runtime(self):
        router, runtime = self._make_router()

        result = router.route_command(
            {
                "command_name": "open",
                "device_id": "ig-xv-24",
                "mock_only": True,
            }
        )

        self.assertTrue(result.success)
        self.assertEqual(getattr(result, "dispatched_via", None), "mock")
        self.assertEqual(runtime.calls, [])