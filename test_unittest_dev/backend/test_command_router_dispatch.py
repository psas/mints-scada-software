from __future__ import annotations

import unittest

from test_unittest_dev.helpers.fakes import FakeBusManager, FakeDeviceRegistry, FakeRuntime
from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip


command_router_module = import_module_or_skip("backend.command_router")
CommandRouter = command_router_module.CommandRouter


class TestCommandRouterDispatch(unittest.TestCase):
    def make_router(self, *, runtime=None, meta=None, snapshot=None):
        runtime = runtime or FakeRuntime()
        meta = meta or {"id": "xv-1", "deviceType": "SolenoidValve", "isControllable": True}
        snapshot = snapshot or {
            "run": {"mode": "live", "status": "running"},
            "bus": {"connected": True, "reconnecting": False},
            "script_runner": {"is_held": False},
            "device_runtime": {"by_id": {}},
        }
        registry = FakeDeviceRegistry(
            {
                "xv-1": {
                    "meta": meta,
                    "runtime": runtime,
                }
            }
        )
        router = CommandRouter(
            device_registry=registry,
            bus_manager=FakeBusManager(),
            state_snapshot_getter=lambda: snapshot,
        )
        return router, runtime

    def test_dry_run_accepts_without_real_dispatch(self):
        router, runtime = self.make_router()
        result = router.route_command(
            {
                "command_name": "open",
                "device_id": "xv-1",
                "dry_run": True,
            }
        )
        self.assertTrue(result.success)
        self.assertEqual(result.dispatched_via, "mock")
        self.assertEqual(runtime.calls, [])

    def test_valve_open_dispatches_runtime_method(self):
        router, runtime = self.make_router()
        result = router.route_command(
            {
                "command_name": "open",
                "device_id": "xv-1",
            }
        )
        self.assertTrue(result.success)
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.dispatched_via, "runtime_method")
        self.assertEqual(runtime.calls[0][0], "open")
        self.assertEqual(result.command_event["device_id"], "xv-1")

    def test_runtime_method_failure_becomes_failed_result(self):
        runtime = FakeRuntime()
        router, _ = self.make_router(
            runtime=runtime,
            meta={"id": "xv-1", "deviceType": "GenericDevice", "isControllable": True},
        )
        result = router.route_command(
            {
                "command_name": "explode",
                "device_id": "xv-1",
            }
        )
        self.assertFalse(result.success)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "boom")

    def test_global_abort_dispatches_to_all_controllable_runtimes(self):
        runtime_a = FakeRuntime()
        runtime_b = FakeRuntime()
        registry = FakeDeviceRegistry(
            {
                "xv-1": {
                    "meta": {"id": "xv-1", "deviceType": "SolenoidValve", "isControllable": True},
                    "runtime": runtime_a,
                },
                "xv-2": {
                    "meta": {"id": "xv-2", "deviceType": "SolenoidValve", "isControllable": True},
                    "runtime": runtime_b,
                },
                "sensor-1": {
                    "meta": {"id": "sensor-1", "deviceType": "PressureSensor", "isControllable": False},
                    "runtime": FakeRuntime(),
                },
            }
        )
        router = CommandRouter(
            device_registry=registry,
            bus_manager=FakeBusManager(),
            state_snapshot_getter=lambda: {
                "run": {"mode": "live", "status": "running"},
                "bus": {"connected": True, "reconnecting": False},
                "script_runner": {"is_held": False},
                "device_runtime": {"by_id": {}},
            },
        )

        result = router.route_command({"command_name": "abort"})
        self.assertTrue(result.success)
        self.assertEqual(result.adapter_name, "global_abort_adapter")
        self.assertEqual(runtime_a.calls[0][0], "abort")
        self.assertEqual(runtime_b.calls[0][0], "abort")
