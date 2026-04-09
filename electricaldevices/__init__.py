# electricaldevices/__init__.py

from .sensors import Thermocouple
from .actuators import Solenoid

__all__ = [
    "Thermocouple",
    "Solenoid",
]