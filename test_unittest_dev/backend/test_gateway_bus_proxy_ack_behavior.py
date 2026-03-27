from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip

gateway_bus_proxy_module = import_module_or_skip("backend.gateway_bus_proxy")
nexus_module = import_module_or_skip("nexus")

GatewayBusProxy = gateway_bus_proxy_module.GatewayBusProxy
DataPacket = nexus_module.DataPacket


class _Resp:
    def __init__(self, type_, payload=None):
        self.type = type_
        self.payload = payload or {}


class _GatewayClientOK:
    def __init__(self):
        self.calls = []

    def send_packet(self, *, device_id, packet):
        self.calls.append((device_id, packet))
        return [_Resp("packet_sent", {})]


class _GatewayClientNoAck:
    def send_packet(self, *, device_id, packet):
        return []


class _GatewayClientError:
    def send_packet(self, *, device_id, packet):
        return [_Resp("error", {"code": "bad_device", "message": "device not found"})]


class _GatewayClientWeird:
    def send_packet(self, *, device_id, packet):
        return [_Resp("unexpected", {})]


class TestGatewayBusProxyAckBehavior(unittest.TestCase):
    def _packet(self):
        return DataPacket(address=0x70)

    def test_send_accepts_packet_sent(self):
        client = _GatewayClientOK()
        proxy = GatewayBusProxy(gateway_client=client, device_id="ig-xv-24")

        proxy.send(self._packet())

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][0], "ig-xv-24")

    def test_send_raises_when_gateway_returns_no_ack(self):
        proxy = GatewayBusProxy(
            gateway_client=_GatewayClientNoAck(),
            device_id="ig-xv-24",
        )

        with self.assertRaises(RuntimeError):
            proxy.send(self._packet())

    def test_send_raises_on_gateway_error(self):
        proxy = GatewayBusProxy(
            gateway_client=_GatewayClientError(),
            device_id="ig-xv-24",
        )

        with self.assertRaises(RuntimeError):
            proxy.send(self._packet())

    def test_send_raises_on_unexpected_response_type(self):
        proxy = GatewayBusProxy(
            gateway_client=_GatewayClientWeird(),
            device_id="ig-xv-24",
        )

        with self.assertRaises(RuntimeError):
            proxy.send(self._packet())