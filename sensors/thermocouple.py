from nexus import GenericSensor, DataPacket

class Thermocouple(GenericSensor):
    def __init__(self, id: int, type: str = "k", simulated: bool = False):
        super().__init__(id=id, simulated=simulated)
        self._type = type

        if self._type == 'k':
            self._no = 3

    def _decodePacket(self, packet: DataPacket):
        super()._decodePacket(packet)
        print("I was called!")