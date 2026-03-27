from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip

device_registry_module = import_module_or_skip("backend.device_registry")
command_router_module = import_module_or_skip("backend.command_router")

DeviceRegistry = device_registry_module.DeviceRegistry
CommandRouter = command_router_module.CommandRouter


def _snapshot() -> dict:
    return {
        "run": {"mode": "live", "status": "running"},
        "bus": {"connected": True, "reconnecting": False},
        "script_runner": {"is_held": False},
        "device_runtime": {"by_id": {}},
    }


class _FakeBusManager:
    pass


class TestLiveRuntimeActualDevices(unittest.TestCase):
    """
    Verifies the actual runtime objects built from local settings expose
    a callable valve command path that the real CommandRouter can use.
    """

    def test_actual_ig_solenoids_have_callable_open_close_style_methods(self):
        registry = DeviceRegistry()
        registry.load_from_settings()

        candidate_names = ("open", "open_valve", "openValve", "set_open", "setOpen",
                           "close", "close_valve", "closeValve", "set_closed", "setClosed")

        for device_id in ("ig-xv-24", "ig-xv-27"):
            runtime = registry.get_runtime(device_id)
            found = [name for name in candidate_names if callable(getattr(runtime, name, None))]
            self.assertTrue(found, msg=f"{device_id} runtime has no supported valve methods")

    def test_command_router_accepts_actual_ig_solenoid_runtime_objects(self):
        registry = DeviceRegistry()
        registry.load_from_settings()

        router = CommandRouter(
            device_registry=registry,
            bus_manager=_FakeBusManager(),
            state_snapshot_getter=_snapshot,
        )

        for device_id, command_name in (
            ("ig-xv-24", "open"),
            ("ig-xv-24", "close"),
            ("ig-xv-27", "open"),
            ("ig-xv-27", "close"),
        ):
            result = router.route_command(
                {
                    "command_name": command_name,
                    "device_id": device_id,
                    "mock_only": False,
                }
            )
            self.assertTrue(result.success, msg=f"{device_id} {command_name} failed: {result}")
            self.assertEqual(getattr(result, "dispatched_via", None), "runtime_method")