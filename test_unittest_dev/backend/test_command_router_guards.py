from __future__ import annotations

import unittest

from test_unittest_dev.helpers.fakes import FakeBusManager, FakeDeviceRegistry, FakeRuntime
from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip


command_router_module = import_module_or_skip("backend.command_router")
CommandRouter = command_router_module.CommandRouter


class TestCommandRouterGuards(unittest.TestCase):
    def make_router(self, *, snapshot=None, entries=None):
        snapshot_value = snapshot or {
            "run": {"mode": "live", "status": "running"},
            "bus": {"connected": True, "reconnecting": False},
            "script_runner": {"is_held": False},
            "device_runtime": {"by_id": {}},
        }
        registry = FakeDeviceRegistry(entries)
        return CommandRouter(
            device_registry=registry,
            bus_manager=FakeBusManager(),
            state_snapshot_getter=lambda: snapshot_value,
        )

    def test_rejects_unsupported_authority_level(self):
        router = self.make_router()
        result = router.route_command(
            {
                "command_name": "noop",
                "authority_level": "wizard",
                "dry_run": True,
            }
        )
        self.assertFalse(result.success)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.rejection_reason, "unsupported_authority_level")

    def test_rejects_commands_in_playback_mode(self):
        router = self.make_router(snapshot={
            "run": {"mode": "playback", "status": "running"},
            "bus": {"connected": True, "reconnecting": False},
            "script_runner": {"is_held": False},
            "device_runtime": {"by_id": {}},
        })
        result = router.route_command(
            {
                "command_name": "open",
                "device_id": "xv-1",
            }
        )
        self.assertFalse(result.success)
        self.assertEqual(result.rejection_reason, "commands_disabled_in_playback")

    def test_rejects_when_run_is_finishing(self):
        router = self.make_router(snapshot={
            "run": {"mode": "live", "status": "finishing"},
            "bus": {"connected": True, "reconnecting": False},
            "script_runner": {"is_held": False},
            "device_runtime": {"by_id": {}},
        })
        result = router.route_command(
            {
                "command_name": "open",
                "device_id": "xv-1",
            }
        )
        self.assertFalse(result.success)
        self.assertEqual(result.rejection_reason, "run_not_accepting_commands")

    def test_rejects_unknown_device(self):
        router = self.make_router()
        result = router.route_command(
            {
                "command_name": "open",
                "device_id": "missing-device",
            }
        )
        self.assertFalse(result.success)
        self.assertEqual(result.rejection_reason, "unknown_device")

    def test_rejects_non_controllable_device(self):
        router = self.make_router(entries={
            "sensor-1": {
                "meta": {"id": "sensor-1", "deviceType": "PressureSensor", "isControllable": False},
                "runtime": FakeRuntime(),
            }
        })
        result = router.route_command(
            {
                "command_name": "open",
                "device_id": "sensor-1",
            }
        )
        self.assertFalse(result.success)
        self.assertEqual(result.rejection_reason, "device_not_controllable")

    def test_rejects_when_bus_is_reconnecting(self):
        router = self.make_router(
            snapshot={
                "run": {"mode": "live", "status": "running"},
                "bus": {"connected": True, "reconnecting": True},
                "script_runner": {"is_held": False},
                "device_runtime": {"by_id": {}},
            },
            entries={
                "xv-1": {
                    "meta": {"id": "xv-1", "deviceType": "SolenoidValve", "isControllable": True},
                    "runtime": FakeRuntime(),
                }
            },
        )
        result = router.route_command({"command_name": "open", "device_id": "xv-1"})
        self.assertFalse(result.success)
        self.assertEqual(result.rejection_reason, "bus_reconnecting")

    def test_rejects_when_device_runtime_inhibits_command(self):
        router = self.make_router(
            snapshot={
                "run": {"mode": "live", "status": "running"},
                "bus": {"connected": True, "reconnecting": False},
                "script_runner": {"is_held": False},
                "device_runtime": {
                    "by_id": {
                        "xv-1": {"command_inhibit": True}
                    }
                },
            },
            entries={
                "xv-1": {
                    "meta": {"id": "xv-1", "deviceType": "SolenoidValve", "isControllable": True},
                    "runtime": FakeRuntime(),
                }
            },
        )
        result = router.route_command({"command_name": "open", "device_id": "xv-1"})
        self.assertFalse(result.success)
        self.assertEqual(result.rejection_reason, "device_command_inhibited")

    def test_rejects_when_device_telemetry_is_stale(self):
        router = self.make_router(
            snapshot={
                "run": {"mode": "live", "status": "running"},
                "bus": {"connected": True, "reconnecting": False},
                "script_runner": {"is_held": False},
                "device_runtime": {
                    "by_id": {
                        "xv-1": {"telemetry_age_seconds": 99.0}
                    }
                },
            },
            entries={
                "xv-1": {
                    "meta": {"id": "xv-1", "deviceType": "SolenoidValve", "isControllable": True},
                    "runtime": FakeRuntime(),
                }
            },
        )
        result = router.route_command(
            {"command_name": "open", "device_id": "xv-1", "stale_after_seconds": 15.0}
        )
        self.assertFalse(result.success)
        self.assertEqual(result.rejection_reason, "device_telemetry_stale")
