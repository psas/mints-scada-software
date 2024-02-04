import can
import struct
import threading
from datapacket import DataPacket
from busrider import BusRider

class Sensor(BusRider):
    def __init__(self, id: int):
        # id of the remote sensor
        self._id = id
        # the canbus the sensor is on
        self._canbus = None
        # the value of the sensor, or None if there was an error
        self.value = None
        self.aux = None
        # the time of the last reading
        self.time = None
        # An event that is triggered when a new packet comes in for this sensor
        self._event = threading.Event()

    def _decodePacket(self, packet: DataPacket):
        ''' Decodes the data portion of a packet '''
        if not packet.err:
            self.value = struct.unpack("<i", packet.data[0:4])[0]
            self.aux = struct.unpack("<i", packet.data[4:8])[0]
        else:
            print("Something bad :(")
            self.value = None

    def _onPacket(self, packet: DataPacket):
        ''' Call this for every packet that comes in '''
        if packet is not None and packet.id == self._id and packet.reply == True:
            # Set the last updated time
            self.time = packet.time
            # Set the value
            print("New value!")
            self._decodePacket(packet)
            # Trigger anything waiting for this sensor
            self._event.set()

    def poll(self):
        ''' Ask for the sensor to take a reading. Use self.value() to get the reading, but note that it may take a moment to come in '''
        # Check if the canbus was initialized
        if self._canbus is None:
            raise RuntimeError("Please initialize the canbus before trying to poll the sensor")
        self._event.clear()
        # Ask the sensor to read
        p = DataPacket(id=self._id, data=[0x80])
        p.send(self._canbus)
        p.print()

    def readValue(self, timeout: float = None):
        ''' Reads a value from the sensor, and waits for the reply before returning the current value. Returns None if the wait timed out '''
        # Check if the canbus was initialized
        if self._canbus is None:
            raise RuntimeError("Please initialize the canbus before trying to poll the sensor")
        # Ask the sensor to read
        self.poll()
        # Wait for the response
        if self._event.wait(timeout):
            # Return the response
            return self.value
        else:
            # No value was read in time
            return None
