from typing import Callable
from nexus import GenericSensor, DataPacket

class Thermocouple(GenericSensor):
    def __init__(self, id: int, type: str = "k", name: str = "Thermocouple", simulated: bool = False, genVal: Callable = None):
        super().__init__(id=id, name=name, simulated=simulated, genVal=genVal)
        self._type = type

        if self._type == 'k':
            self._no = 3

    @property
    def c(self):
        # TODO put in the correct equations here
        # return self.value * 28.4 if self.value is not None else -999
        return self.value if self.value is not None else -999
    
    def logValue(self):
        return self.c