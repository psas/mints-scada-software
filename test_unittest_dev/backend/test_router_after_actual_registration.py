from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip

device_registry_module = import_module_or_skip("backend.device_registry")
command_router_module = import_module_or_skip("backend.command_router")

DeviceRegistry = device_registry_module.DeviceRegistry
CommandRouter = command_router_module.CommandRouter


class _RecordingBus:
    def __init__(self):
        self.riders = []

    def addRider(self, rider):
        self.riders.append(rider)


class _FakeBusManager:
    pass


def _snapshot() -> dict:
    return {
        "run": {"mode": "live", "status": "running"},
        "bus": {"connected": True, "reconnecting": False},
        "script_runner": {"is_held": False},
        "device_runtime": {"by_id": {}},
    }


class TestRouterAfterActualRegistration(unittest.TestCase):
    def test_router_rejects_before_registration(self):
        registry = DeviceRegistry()
        registry.load_from_settings()

        router = CommandRouter(
            device_registry=registry,
            bus_manager=_FakeBusManager(),
            state_snapshot_getter=_snapshot,
        )

        result = router.route_command(
            {
                "command_name": "open",
                "device_id": "ig-xv-24",
                "mock_only": False,
            }
        )

        self.assertFalse(result.success)
        self.assertEqual(result.rejection_reason, "device_not_live_registered")

    def test_router_accepts_after_registration(self):
        registry = DeviceRegistry()
        registry.load_from_settings()

        bus = _RecordingBus()
        reg = registry.register_active_devices_with_bus(bus)

        self.assertIn("ig-xv-24", reg["registered_ids"])

        runtime = registry.get_runtime("ig-xv-24")
        self.assertTrue(getattr(runtime, "live_registered", False))

        # Isolate router/registration guard from actual bus-send behavior.
        # We only want to prove that once the device is live-registered,
        # CommandRouter no longer rejects it as device_not_live_registered.
        runtime.open = lambda *args, **kwargs: None
        runtime.close = lambda *args, **kwargs: None

        router = CommandRouter(
            device_registry=registry,
            bus_manager=_FakeBusManager(),
            state_snapshot_getter=_snapshot,
        )

        result = router.route_command(
            {
                "command_name": "open",
                "device_id": "ig-xv-24",
                "mock_only": False,
            }
        )

        self.assertTrue(
            result.success,
            msg=(
                f"status={result.status!r}, "
                f"adapter_name={result.adapter_name!r}, "
                f"rejection_reason={result.rejection_reason!r}, "
                f"interlock_reason={result.interlock_reason!r}, "
                f"error={result.error!r}, "
                f"state_reasons={result.state_reasons!r}, "
                f"result_summary={result.result_summary!r}"
            ),
        )
        self.assertEqual(result.dispatched_via, "runtime_method")
        