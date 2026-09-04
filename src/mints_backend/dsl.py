from PySide6.QtCore import QObject

from mints_backend.device_manager import DeviceRegistry
from mints_backend.devices import Device, OutputState


class Mints(QObject):
    def __init__(self, device_registry: DeviceRegistry):
        self.device_registry = device_registry

    def open(self, valve_name: str) -> None:
        output: Device = self.device_registry.get_by_name(valve_name)
        output.set_state(OutputState.High)

    def open_valves(self, valve_names: list) -> None:
        for name in valve_names:
            self.open(name)

    def close(self, valve_name: str) -> None:
        output: Device = self.device_registry.get_by_name(valve_name)
        output.set_state(OutputState.Low)

    def close_valves(self, valve_names: list) -> None:
        for name in valve_names:
            self.close(name)

    def read(self, sensor_name: str) -> None:
        raise NotImplementedError

    def read_sensors(self, sensor_names: list) -> None:
        for name in sensor_names:
            self.read(name)

    def wait(self) -> None:
        raise NotImplementedError
