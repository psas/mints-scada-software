from nexus import DataPacket, BusCommands, GenericSensor
import struct



class GenericActuator(GenericSensor):
    def __init__(self, id: int, name: str = "GenericActuator", simulated: bool = False):
        super().__init__(id=id, name=name, simulated=simulated)
        self.value = False

    def set(self, state: bool | int):
        # Update the state
        self.value = state
        # Send the command to change
        p = DataPacket(self._id, cmd=BusCommands.WRITE_VALUE, data=self._packValue())
        self._bus.send(p)

    def _decodePacket(self, packet: DataPacket):
        ''' Decodes the data portion of a packet '''
        if not packet.err:
            # Set value command
            if packet.cmd == BusCommands.WRITE_VALUE:
                self.value, self.aux = struct.unpack(self.STRUCT_FORMAT, packet.data)
                return
        super()._decodePacket(packet=packet)

    def _onPacket(self, packet: DataPacket):
        ''' Call this for every packet that comes in '''
        if packet is not None and packet.id == self._id:
            # Handle the set command
            if not packet.reply and self._simulated:
                if packet.cmd == BusCommands.WRITE_VALUE:
                    # Actually update the values
                    self.value, self.aux = struct.unpack(self.STRUCT_FORMAT, packet.data)
                    # Send a reply with the current value of the actuator.
                    # Must be repacked to ensure any unpacking errors are included.
                    reply = packet.getReply(self._packValue())
                    self._bus.send(reply)
                    self._bus.printDbgPacket(reply, "Sent reply")
                    # Notify anyone who cares, then don't go to the parent's onPacket
                    self.updateListeners()
                    return
            # Call onPacket from GenericSensor if we don't have anything special to do with it
            super()._onPacket(packet=packet)

    def readSensor(self):
        ''' This won't change unless requested to, so we don't have to do anything here '''
        pass

    def setActuator(self):
        ''' This would actually set the output if this was a real sensor '''
        pass