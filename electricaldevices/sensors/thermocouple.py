# electricaldevices/sensors/thermocouple.py
from collections.abc import Callable
from nexus import GenericSensor


class Thermocouple(GenericSensor):
    def __init__(
        self,
        id: int,
        device_id: str = "Thermocouple",
        *,
        tc_type: str = "k",
        simulated: bool = False,
        genVal: Callable | None = None,
    ):
        super().__init__(
            id=id,
            device_id=device_id,
            simulated=simulated,
            genVal=genVal,
        )
        self._type = tc_type

        if self._type == "k":
            self._no = 3

    @property
    def c(self):
        return self.value if self.value is not None else -999

    def logValue(self):
        return self.c
