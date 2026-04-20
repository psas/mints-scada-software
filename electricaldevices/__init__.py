"""electricaldevices/__init__.py

Public exports for the electrical device package.

This package re-exports the primary actuator and sensor classes used by higher
layers so callers can import the common device types from a single package
boundary.
"""

from .sensors import Thermocouple
from .actuators import Solenoid

__all__ = [
    "Thermocouple",
    "Solenoid",
]
