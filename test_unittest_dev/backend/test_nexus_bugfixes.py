"""Regression tests for nexus Bus/DataPacket bugfixes."""

import unittest
from unittest.mock import MagicMock, patch

from nexus.datapacket import DataPacket
from nexus.busrider import BusRider


class TestDataPacketTruncation(unittest.TestCase):
    """DataPacket._prepare must preserve exactly 6 payload bytes."""

    def test_six_byte_payload_preserved(self):
        pkt = DataPacket(id=0x01, data=[1, 2, 3, 4, 5, 6])
        self.assertEqual(list(pkt.data), [1, 2, 3, 4, 5, 6])

    def test_seven_byte_payload_truncated_to_six(self):
        pkt = DataPacket(id=0x01, data=[1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(len(pkt.data), 6)
        self.assertEqual(list(pkt.data), [1, 2, 3, 4, 5, 6])

    def test_eight_byte_payload_truncated_to_six(self):
        pkt = DataPacket(id=0x01, data=[10, 20, 30, 40, 50, 60, 70, 80])
        self.assertEqual(len(pkt.data), 6)
        self.assertEqual(list(pkt.data), [10, 20, 30, 40, 50, 60])

    def test_short_payload_not_modified(self):
        pkt = DataPacket(id=0x01, data=[1, 2, 3])
        self.assertEqual(list(pkt.data), [1, 2, 3])

    def test_default_payload_is_six_zeros(self):
        pkt = DataPacket(id=0x01)
        self.assertEqual(len(pkt.data), 6)


class TestRemoveRiderDisconnect(unittest.TestCase):
    """Bus.removeRider must call rider._connectBus(None), not a missing method."""

    @patch("nexus.bus.can.ThreadSafeBus")
    def test_remove_rider_calls_connect_bus_none(self, mock_can_cls):
        from nexus.bus import Bus

        bus = Bus(channel="/dev/null", bitrate=500000)

        rider = BusRider(id=0x10, simulated=True)
        rider._connectBus = MagicMock()

        bus._Bus__running = True
        bus._riders.append(rider)

        bus.removeRider(rider)

        rider._connectBus.assert_called_once_with(None)
        self.assertNotIn(rider, bus._riders)

    @patch("nexus.bus.can.ThreadSafeBus")
    def test_remove_rider_no_attribute_error(self, mock_can_cls):
        from nexus.bus import Bus

        bus = Bus(channel="/dev/null", bitrate=500000)

        rider = BusRider(id=0x10, simulated=True)
        bus._Bus__running = True
        bus._riders.append(rider)

        try:
            bus.removeRider(rider)
        except AttributeError:
            self.fail("removeRider raised AttributeError — likely calling a non-existent method")


if __name__ == "__main__":
    unittest.main()
