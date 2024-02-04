import can
from datapacket import DataPacket

class BusRider():
    def __init__(self):
        self._canbus = None

    def _setBus(self, canbus: can.ThreadSafeBus):
        self._canbus = canbus

    def _onPacket(self, packet: DataPacket):
        pass