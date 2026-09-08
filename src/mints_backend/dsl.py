import csv
from datetime import UTC, datetime
from pathlib import Path
from time import sleep

from mints_backend.device_manager import (
    DeviceManager,
    DeviceRegistry,
    try_setup_device_manager,
)
from mints_backend.devices import Device, OutputState


class Mints:
    def __init__(self):
        self.device_manager: DeviceManager = try_setup_device_manager()
        self.device_registry: DeviceRegistry = self.device_manager.device_registry
        data_dir = Path.cwd() / "data"
        if not Path.exists(data_dir):
            Path.mkdir(data_dir)
        self.data_dir = data_dir
        now = datetime.now(UTC)
        self.csv_file_path = data_dir / f"{now.strftime('%Y-%m-%d_%H:%M:%S')}.csv"
        self.csv_file = None
        self.csv_writer = None

    def __enter__(self):
        self.csv_file = Path.open(self.csv_file_path, "w", newline="")
        csv_fieldnames = [sensor.name for sensor in self.device_registry.sensors]
        self.csv_writer = csv.DictWriter(self.csv_file, csv_fieldnames)
        self.csv_writer.writeheader()
        return self

    def open(self, valve_name: str) -> None:
        output: Device = self.device_registry.get_by_name(valve_name)
        output.set_state(OutputState.High)

    def open_valves(self, valve_names: list[str]) -> None:
        for name in valve_names:
            self.open(name)

    def close(self, valve_name: str) -> None:
        output: Device = self.device_registry.get_by_name(valve_name)
        output.set_state(OutputState.Low)

    def close_valves(self, valve_names: list) -> None:
        for name in valve_names:
            self.close(name)

    def read(self, sensor_name: str) -> None:
        sensor = self.device_registry.get_by_name(sensor_name)
        sensor.subscribe(lambda val: self.append_to_csv(sensor.name, val))

    def read_sensors(self, sensor_names: list[str]) -> None:
        for name in sensor_names:
            self.read(name)

    def append_to_csv(self, name: str, val: int):
        if self.csv_writer is None:
            raise RuntimeError("No CSV writer found")
        self.csv_writer.writerow({name: val})

    def __exit__(self, *args) -> None:
        self.device_manager.teardown()
        if self.csv_file is None:
            return
        self.csv_file.close()

    @staticmethod
    def wait(s: int) -> None:
        sleep(s)
