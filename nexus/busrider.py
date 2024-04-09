from nexus import DataPacket, Bus, BusCommands
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
    def __init__(self, id: int, name = "BusRider", simulated: bool = False):
        # ID of the remote device
        self._id = id
        
        # The serial number of the sensor
        # TODO check this to help ensure that the correct sensor is at this address
        self._serial = None

        # The bus the rider rides on
        self._bus = None

        # The name of the rider
        self.name = name

        self._simulated = simulated
        ''' If the sensor is simulated. DO NOT CHANGE THIS '''

        self.time = None
        ''' the time of the last reading '''

        # An event that is triggered when a new packet comes in for this sensor
        self._event = threading.Event()
        self._nextSequenceID = 0

    def _connectBus(self, bus: Bus):
        self._bus = bus
        if self._bus is not None and not self._simulated:
            # Get the ID of the sensor
            request = DataPacket(id=self._id, cmd=BusCommands.READ_ID_LOW)
            request.send(bus)

    def _onPacket(self, packet: DataPacket):
        ''' Call this for every packet that comes in '''
        if packet is not None and packet.id == self._id:
            if packet.reply:
                if packet.cmd == BusCommands.READ_ID_LOW:
                    self._serial = packet.data
                else:
                    # Set the last updated time
                    self.time = packet.time
                    # Set the value
                    self._decodePacket(packet)
                    # Trigger anything waiting for this sensor
                    self._event.set()
    
    def _decodePacket(self):
        ''' Implement this in child classes '''
        pass

    def poll():
        ''' Implement this in child classes '''
        pass
