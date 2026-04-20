"""electricaldevices/actuators/__init__.py

Public actuator exports for the electrical device package.

This subpackage re-exports the actuator classes intended to be imported from the
actuator package boundary.
"""

from .solenoid import Solenoid

__all__ = [
    "Solenoid",
]
