from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip

device_registry_module = import_module_or_skip("backend.device_registry")
gateway_bus_proxy_module = import_module_or_skip("backend.gateway_bus_proxy")

DeviceRegistry = device_registry_module.DeviceRegistry
GatewayBusProxy = gateway_bus_proxy_module.GatewayBusProxy


class _SpyGatewayClient:
    def __init__(self):
        self.calls = []

    def send_packet(self, *, device_id, packet):
        self.calls.append(
            {
                "device_id": device_id,
                "packet": packet,
                "packet_id": getattr(packet, "id", None),
            }
        )
        return [type("Resp", (), {"type": "packet_sent", "payload": {}})()]


class TestGatewayProxyCallsGatewayClient(unittest.TestCase):
    def test_runtime_open_uses_gateway_client_with_expected_device_id_and_address(self):
        registry = DeviceRegistry()
        registry.load_from_settings()

        runtime = registry.get_runtime("ig-xv-24")
        runtime.live_registered = True

        client = _SpyGatewayClient()
        runtime._bus = GatewayBusProxy(
            gateway_client=client,
            device_id="ig-xv-24",
        )

        runtime.open()

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["device_id"], "ig-xv-24")
        self.assertEqual(client.calls[0]["packet_id"], 0x70)

    def test_runtime_close_uses_gateway_client_with_expected_device_id_and_address(self):
        registry = DeviceRegistry()
        registry.load_from_settings()

        runtime = registry.get_runtime("ig-xv-24")
        runtime.live_registered = True

        client = _SpyGatewayClient()
        runtime._bus = GatewayBusProxy(
            gateway_client=client,
            device_id="ig-xv-24",
        )

        runtime.close()

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["device_id"], "ig-xv-24")
        self.assertEqual(client.calls[0]["packet_id"], 0x70)