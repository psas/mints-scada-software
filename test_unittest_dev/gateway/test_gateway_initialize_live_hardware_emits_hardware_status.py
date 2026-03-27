from __future__ import annotations

import types
import unittest
from types import SimpleNamespace

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip

gateway_service_module = import_module_or_skip("gateway.service")
ipc_models = import_module_or_skip("gateway.ipc_models")

GatewayService = gateway_service_module.GatewayService
GatewayIPCMessage = ipc_models.GatewayIPCMessage


class _FakeBusManager:
    sender = "fake-sender"
    bitrate = 125000

    def initialize_live_hardware(self, device_registry):
        del device_registry
        return SimpleNamespace(
            registered_ids=["ig-xv-24"],
            skipped_ids=["ig-xv-27"],
            registered_count=1,
            skipped_count=1,
            sender=self.sender,
            bitrate=self.bitrate,
            already_running=False,
        )


class TestGatewayInitializeLiveHardwareEmitsHardwareStatus(unittest.TestCase):
    def _make_service_like(self):
        service = GatewayService.__new__(GatewayService)
        service.bus_manager = _FakeBusManager()
        service.device_registry = object()
        service._bus_connected = False
        service._last_registered_ids = []
        service._last_skipped_ids = []

        synced_payloads: list[dict] = []
        service._sync_hardware_status_to_backend = lambda payload: synced_payloads.append(dict(payload))

        service.handle_message = types.MethodType(GatewayService.handle_message, service)
        return service, synced_payloads

    def test_initialize_live_hardware_yields_hardware_status_message(self):
        service, synced_payloads = self._make_service_like()

        message = GatewayIPCMessage(type="initialize_live_hardware", payload={})
        responses = list(service.handle_message("client-1", message))

        self.assertEqual(len(responses), 1)

        response = responses[0]
        self.assertEqual(response.type, "hardware_status")
        self.assertEqual(response.payload["connected"], True)
        self.assertEqual(response.payload["reconnecting"], False)
        self.assertEqual(response.payload["status"], "connected")
        self.assertEqual(response.payload["reason"], "gateway_initialize_live_hardware")
        self.assertEqual(response.payload["sender"], "fake-sender")
        self.assertEqual(response.payload["bitrate"], 125000)
        self.assertEqual(response.payload["registered_ids"], ["ig-xv-24"])
        self.assertEqual(response.payload["skipped_ids"], ["ig-xv-27"])
        self.assertEqual(response.payload["registered_count"], 1)
        self.assertEqual(response.payload["skipped_count"], 1)
        self.assertEqual(response.payload["already_running"], False)
        self.assertEqual(response.payload["packet_listener_attached"], True)
        self.assertTrue(response.payload["wall_time"])

        self.assertEqual(len(synced_payloads), 1)
        self.assertEqual(synced_payloads[0]["registered_ids"], ["ig-xv-24"])
        self.assertEqual(synced_payloads[0]["skipped_ids"], ["ig-xv-27"])