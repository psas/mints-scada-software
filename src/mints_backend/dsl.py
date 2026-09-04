from PySide6.QtCore import QObject

from mints_backend.device_manager import DeviceRegistryType
from mints_backend.devices import Output, OutputState


class Mints(QObject):
    def __init__(self, device_registry: DeviceRegistryType):
        self.device_registry = device_registry

    def open(self, valve: str) -> None:
        output: Output = next(
            iter(
                [
                    output
                    for output in self.device_registry
                    if output.name == valve and isinstance(output, Output)
                ]
            )
        )
        output.set_state(OutputState.High)
