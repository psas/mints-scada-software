# electricaldevices/sensors/thermocouple.py

"""Thermocouple sensor implementation built on the generic sensor base."""


from collections.abc import Callable
from nexus import GenericSensor


class Thermocouple(GenericSensor):
    """Thermocouple sensor wrapper over the generic sensor runtime.

    The class forwards the common sensor setup to ``GenericSensor`` and stores
    the thermocouple type used by this instance. The current implementation
    assigns sensor number ``3`` for type ``"k"`` and exposes a Celsius-style
    reading helper that falls back to ``-999`` when no value is available.
    """

    def __init__(
        self,
        id: int,
        device_id: str = "Thermocouple",
        *,
        tc_type: str = "k",
        simulated: bool = False,
        genVal: Callable | None = None,
    ):
        """Initialize a thermocouple sensor instance.

        Args:
            id: Bus or device identifier forwarded to ``GenericSensor``.
            device_id: Human-readable device identifier used by the base sensor.
            tc_type: Thermocouple type label for this instance.
            simulated: Whether the sensor should run in simulated mode.
            genVal: Optional generator callback used by simulated sensors.
        """
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
        """Return the current sensor reading or the no-data sentinel.

        Returns:
            The current sensor value when available. Returns ``-999`` when the
            base sensor has no reading.
        """
        return self.value if self.value is not None else -999

    def logValue(self):
        """Return the value used by the logging path.

        Returns:
            The current Celsius-style reading exposed by ``c``.
        """
        return self.c
