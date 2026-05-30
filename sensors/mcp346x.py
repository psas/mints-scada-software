from typing import Callable
from nexus import GenericSensor, DataPacket
import ctypes

class MCP346x(GenericSensor):
    def __init__(self, id: int, name: str = "ADC", simulated: bool = False, genVal: Callable = None, ref: float = 2.4, gain: float = 1/3, **kwargs):
        super().__init__(id=id, name=name, simulated=simulated, genVal=genVal, **kwargs)
        self._ref = ref
        self._gain = gain

    @property
    def ref(self):
        return self._ref

    @property
    def gain(self):
        return self._gain

    @property
    def v(self):
        # TODO put actual value here
        reading = float(ctypes.c_short(self.value).value)
        return (reading / 32768.0) * self.ref / self.gain

    def logValue(self):
        return self.v