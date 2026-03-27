from __future__ import annotations

import types
import unittest
from types import SimpleNamespace

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip

service_module = import_module_or_skip("backend.service")
state_store_module = import_module_or_skip("backend.state_store")
device_registry_module = import_module_or_skip("backend.device_registry")

BackendService = service_module.BackendService
StateStore = state_store_module.StateStore
DeviceRegistry = device_registry_module.DeviceRegistry


class _NoopHealth:
    def record_system_event(self, *args, **kwargs):
        return None


class _NoopMonitor:
    def sample_once(self):
        return None


class TestGatewayHardwareStatusSync(unittest.TestCase):
    def _make_service_like(self):
        svc = BackendService.__new__(BackendService)
        svc.device_registry = DeviceRegistry()
        svc.device_registry.load_from_settings()
        svc.state_store = StateStore(
            service_name="test-backend",
            backend_started_at="2026-03-26T00:00:00.000Z",
        )
        svc.bus_manager = SimpleNamespace(sender="test", bitrate=125000)
        svc.health = _NoopHealth()
        svc.health_monitor = _NoopMonitor()
        svc._gateway_last_registered_ids = []
        svc._gateway_last_skipped_ids = []
        svc._gateway_bus_proxies_by_id = {}

        for name in (
            "_normalize_mapping_payload",
            "_get_optional_string",
            "_get_optional_int",
            "_build_device_inventory_with_live_registration",
            "_apply_gateway_hardware_status",
        ):
            setattr(svc, name, types.MethodType(getattr(BackendService, name), svc))

        svc._attach_gateway_bus_proxies = lambda registered_ids: None
        svc._detach_all_gateway_bus_proxies = lambda: None

        return svc

    def test_gateway_status_marks_runtime_live_registered_for_registered_ids(self):
        svc = self._make_service_like()

        runtime = svc.device_registry.get_runtime("ig-xv-24")
        self.assertFalse(bool(getattr(runtime, "live_registered", False)))

        svc._apply_gateway_hardware_status(
            {
                "connected": True,
                "reconnecting": False,
                "registered_ids": ["ig-xv-24"],
                "skipped_ids": [],
            },
            record_health=False,
        )

        runtime = svc.device_registry.get_runtime("ig-xv-24")
        self.assertTrue(bool(getattr(runtime, "live_registered", False)))