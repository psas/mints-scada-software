import can
from nexus import DataPacket
import threading

# Message send format
# First byte is message identifier. Any byte can be used. This byte will become the first byte in the reply.
# Second byte is command
# Remaining 6 bytes are arguments

# Message Receive format
# First byte is sequency identifier. This will be the same as in the message that was sent.
# Remaining 7 bytes are reply data

# Commands 0x00 and 0x01 are GET_SERIAL_LOW and GET_SERIAL_HIGH

# NEVER change if a device is simulated.

class BusRider():
    def __init__(self, id: int, simulated: bool = False):
        # ID of the remote device
        self._id = id
        self._serial = None
        self._canbus = None

        self._simulated = simulated
        ''' If the sensor is simulated. DO NOT CHANGE THIS '''

        self.time = None
        ''' the time of the last reading '''

        # An event that is triggered when a new packet comes in for this sensor
        self._event = threading.Event()
        self._nextSequenceID = 0

    def _connectBus(self, canbus: can.ThreadSafeBus):
        self._canbus = canbus
        if self._canbus is not None and not self._simulated:
            # Get the ID of the sensor
            request = DataPacket(id=self._id, cmd=0x00)
            request.send(canbus)

    def _onPacket(self, packet: DataPacket):
        ''' Call this for every packet that comes in '''
        if packet is not None and packet.id == self._id:
            if packet.reply:
                if packet.data[0] == 0x00:
                    self._serial = packet.data
                else:
                    # Set the last updated time
                    self.time = packet.time
                    # Set the value
                    self._decodePacket(packet)
                    # Trigger anything waiting for this sensor
                    self._event.set()
    
    def _decodePacket(self):
        pass
