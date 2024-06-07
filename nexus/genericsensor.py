from typing import Callable
import struct
import random
from nexus import DataPacket, BusRider, BusCommands
import numpy as np
import logging

class GenericSensor(BusRider):
    STRUCT_FORMAT = "<IH"
    BASE_HISTORY_SIZE = 1000
    def __init__(self, id: int, name: str = "GenericSensor", simulated: bool = False, genVal: Callable = None):
        super().__init__(id, name=name, simulated=simulated)
        self.log = logging.getLogger("genericsensor")
        # the value of the sensor, or None if there was an error. Must be an unsigned 4 byte int
        self.value = None
        # An auxiliary output from the sensor. Must be an unsigned 2 byte int.
        self.aux = None
        if genVal != None:
            self.genVal = staticmethod(genVal)
        # Things that happen when packets come in
        # These will be called for every packet that comes in that is for this sensor.
        # The listener should check that any other conditions it needs are met.
        # These are called after the packet is processed and values or errors have been parsed.
        # The updated sensor is passed as the first argument.
        self._updateListeners = []
        self.history = np.zeros((2,self.BASE_HISTORY_SIZE))
        self.historyIndex = 0

    def genVal(self):
        return random.randint(0, (2**32)-1)

    # TODO use the sequence number to determine what to do with an incoming packet
    def _decodePacket(self, packet: DataPacket):
        ''' Decodes the data portion of a packet '''
        if not packet.err:
            # TODO ID parsing should be done at the BusRider level, not here
            if packet.cmd == BusCommands.READ_ID_LOW:
                # TODO make the sent data actually useful
                pass
            elif packet.cmd == BusCommands.READ_ID_HIGH:
                # TODO make the sent data actually useful
                pass
            # Get value command
            elif packet.cmd == BusCommands.READ_VALUE:
                # Read the actual value
                self.value, self.aux = struct.unpack(self.STRUCT_FORMAT, packet.data)
                # Expand history if needed
                if self.historyIndex == np.shape(self.history)[1]:
                    self.history = np.append(self.history, np.zeros((2, self.BASE_HISTORY_SIZE)), 1)
                # Add it to the history
                self.history[:,self.historyIndex] = (self.time, self.logValue())
                self.historyIndex += 1
            else:
                # TODO figure out what should happen here
                pass 
        else:
            self.log.error("Something bad :( The packet was an error")
            self.value = None

    def _onPacket(self, packet: DataPacket):
        ''' Call this for every packet that comes in '''
        if packet is not None and packet.id == self._id:
            if packet.reply:
                # Check if this was a failed ID claim and error if it was
                if packet.cmd == BusCommands.CLAIM_ID and packet.err:
                    self.log.fatal(f"Nooooo something is wrong! A device reported this ID {self._id:02X} as taken!")
                else:
                    # Set the last updated time
                    self.time = packet.time
                    # Set the value
                    self._decodePacket(packet)
                    # Trigger anything waiting for this sensor
                    self._event.set()
            else:
                reply = packet.getReply()
                # Get ID command
                if packet.cmd == BusCommands.READ_ID_LOW:
                    # TODO make the sent data actually useful
                    reply.data=[0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
                elif packet.cmd == BusCommands.READ_ID_HIGH:
                    # TODO make the sent data actually useful
                    reply.data=[0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
                # Get value command
                elif packet.cmd == BusCommands.READ_VALUE:
                    self.readSensor()
                    if self.value is not None:
                        reply.data = self._packValue()
                    else:
                        reply.err = True
                elif packet.cmd == BusCommands.CLAIM_ID:
                    # Someone wanted this ID, that's fine. Don't need to say anything.
                    reply = None
                else:
                    reply.err=True
                if reply is not None:
                    self._bus.send(reply)
                    self._bus.printDbgPacket(reply, "Sent reply")
            self.updateListeners()
    
    def updateListeners(self):
        ''' Let anyone who cares know that the value of this just changed '''
        for listener in self._updateListeners:
            listener(self)

    def _packValue(self) -> bytearray:
        ''' Gets the value of the sensor as a bytearray ready to be sent on the bus '''
        return struct.pack(self.STRUCT_FORMAT, self.value, self.aux or 0)

    def addListener(self, packetListener: Callable):
        self._updateListeners.append(packetListener)

    def poll(self):
        ''' Ask for the sensor to take a reading. Use self.value() to get the reading, but note that it may take a moment to come in '''
        # Only poll real sensors
        if self._simulated:
            return
        # Check if the canbus was initialized
        if self._bus is None:
            raise RuntimeError("Please initialize the bus before trying to poll the sensor")
        self._event.clear()
        # Ask the sensor to read
        p = DataPacket(id=self._id, cmd=BusCommands.READ_VALUE)
        self._bus.send(p)
        self._bus.printDbgPacket(p, "Sent poll")

    def readValue(self, timeout: float = None, onFail: Callable[..., None] = None):
        ''' Reads a value from the sensor, and waits for the reply before returning the current value. Returns None if the wait timed out '''
        # If the sensor is simulated, simply return the value
        if self._simulated:
            return self.value
        # Check if the canbus was initialized
        if self._bus is None:
            raise RuntimeError("Please initialize the canbus before trying to poll the sensor")
        # Ask the sensor to read
        self.poll()
        # Wait for the response
        if self._event.wait(timeout):
            # Return the response
            return self.value
        else:
            # No value was read in time
            if onFail is not None:
                onFail()
            return None

    def readSensor(self):
        ''' Reads a local sensor. Usually this would be done in preperation to answer a poll request. '''
        if self._simulated:
            self.value = self.genVal()
            self.log.info("My value is", self.value)

    def logValue(self):
        return self.value
