import unittest

from backend.gateway_bus_proxy import GatewayBusProxy
from nexus import DataPacket


class _FakeMessage:
    def __init__(self, msg_type: str, payload: dict | None = None):
        self.type = msg_type
        self.payload = payload or {}


class _FakeGatewayClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def send_packet(self, *, device_id: str, packet: DataPacket):
        self.calls.append(
            {
                "device_id": device_id,
                "packet_id": packet.id,
                "seq": packet.seq,
                "cmd": packet.cmd,
                "reply": packet.reply,
                "err": packet.err,
                "rsvd": packet.rsvd,
                "data": list(packet.data),
            }
        )
        return list(self._responses)


class TestGatewayBusProxy(unittest.TestCase):
    def test_send_accepts_packet_sent_without_raw_event_payload(self):
        client = _FakeGatewayClient(
            [
                _FakeMessage(
                    "packet_sent",
                    {
                        "device_id": "XV-1",
                        "packet_id": 12,
                        "seq": 3,
                        "cmd": 1,
                    },
                )
            ]
        )
        proxy = GatewayBusProxy(gateway_client=client, device_id="XV-1")

        packet = DataPacket(
            id=12,
            seq=3,
            cmd=1,
            reply=False,
            err=False,
            rsvd=False,
            data=[1, 2, 3, 4, 5, 6],
        )

        proxy.send(packet)

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["device_id"], "XV-1")
        self.assertEqual(client.calls[0]["packet_id"], 12)

    def test_send_raises_when_gateway_returns_error(self):
        client = _FakeGatewayClient(
            [
                _FakeMessage(
                    "error",
                    {"code": "send_packet_failed", "message": "gateway rejected"},
                )
            ]
        )
        proxy = GatewayBusProxy(gateway_client=client, device_id="XV-2")

        packet = DataPacket(
            id=22,
            seq=1,
            cmd=1,
            reply=False,
            err=False,
            rsvd=False,
            data=[0, 0, 0, 0, 0, 0],
        )

        with self.assertRaises(RuntimeError):
            proxy.send(packet)

    def test_send_raises_on_unexpected_response_type(self):
        client = _FakeGatewayClient([_FakeMessage("pong", {})])
        proxy = GatewayBusProxy(gateway_client=client, device_id="XV-3")

        packet = DataPacket(
            id=33,
            seq=1,
            cmd=1,
            reply=False,
            err=False,
            rsvd=False,
            data=[0, 0, 0, 0, 0, 0],
        )

        with self.assertRaises(RuntimeError):
            proxy.send(packet)