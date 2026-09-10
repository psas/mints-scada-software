from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import pyqtgraph as pg
from pandas import DataFrame, read_csv
from PySide6.QtCore import QEventLoop, QTimer

from mints_backend.device_manager import (
    DeviceManager,
    DeviceRegistry,
    try_setup_device_manager,
)
from mints_backend.devices import UPDATE_PERIOD, Device, Output, OutputState, Sensor

TS_COL_NAME = "time (s)"

RowType = dict[str, float | None]


class Mints:
    def __init__(self, sampling_rate_ms: float = UPDATE_PERIOD):
        """
        Mints DSL class
        Meant to be used as a context manager
        By default uses the same sampling rate as the graphs
        Example usage:
        # Opens a valve and reads a sensor for 10 seconds.
        # Displays a plot of collected data on exit
        with Mints() as mints:
            mints.open("IG-XV-27")
            mints.read("TT5")
            mints.runfor(10000)
            mints.plot()
        """
        self.qapp = pg.mkQApp()
        self.sampling_rate = sampling_rate_ms
        self.device_manager: DeviceManager = try_setup_device_manager()
        self.device_registry: DeviceRegistry = self.device_manager.device_registry
        data_dir = Path.cwd() / "data"
        if not Path.exists(data_dir):
            data_dir.mkdir()
        self.data_dir = data_dir
        now = datetime.now(UTC)
        self.csv_file_path = Path(data_dir / f"{now.strftime('%Y-%m-%d_%H:%M:%S')}.csv")
        self.samples: list[Sample] = []
        self.time_start = perf_counter()
        self.do_plot_at_end = False
        self.selected_sensors: list[str] = []

    def __enter__(self):
        return self

    def open(self, valve_name: str) -> None:
        """
        Open a single valve
        """
        output: Device = self.device_registry.get_by_name(valve_name)
        output.set_state(OutputState.High)

    def open_valves(self, valve_names: list[str]) -> None:
        """
        Open a list of valves
        """
        for name in valve_names:
            self.open(name)

    def close(self, valve_name: str) -> None:
        """
        Close a single valve
        """
        output: Device = self.device_registry.get_by_name(valve_name)
        output.set_state(OutputState.Low)

    def close_valves(self, valve_names: list) -> None:
        """
        Close a list of valves
        """
        for name in valve_names:
            self.close(name)

    def close_all(self):
        """
        Close all valves in the registry
        """
        for valve in self.device_registry.outputs:
            valve.set_state(OutputState.Low)

    def read(self, sensor_name: str) -> None:
        """
        Read a single sensor at regular intervals
        """
        self.selected_sensors.append(sensor_name)
        dev: Sensor | Output = self.device_registry.get_by_name(sensor_name)
        match dev:
            case Sensor() as sensor:
                sensor.subscribe(
                    lambda val: self._take_sample(sensor.id, sensor.name, val),
                    self.sampling_rate,
                )
            case _:
                raise TypeError("Expected Sensor, found %s", type(dev))

    def read_sensors(self, sensor_names: list[str]) -> None:
        """
        Read a list of sensors at regular intervals
        """
        for name in sensor_names:
            self.read(name)

    def read_all(self) -> None:
        """
        Set all sensors in the registry to be read at regular
        """
        for sensor in self.device_registry.sensors:
            self.read(sensor.name)

    def plot(self):
        """
        Open a window displaying the collected CSV on a pyqtgraph plot on script end
        """
        self.do_plot_at_end = True

    @staticmethod
    def runfor(time_ms: int) -> None:
        """
        Run an event loop to process sensor subscriptions for time_ms milliseconds
        Can be used as a pseudo-sleep method too if not reading sensors
        """
        loop = QEventLoop()
        QTimer.singleShot(time_ms, loop.quit)
        loop.exec()

    def _take_sample(self, sensor_id: int, sensor_name: str, val: int):
        ts = perf_counter() - self.time_start
        sample = Sample(sensor_id, sensor_name, ts, val)
        self.samples.append(sample)

    def _process_csv(self):
        """
        Places samples into 0.1 second buckets, then constructs each row of the csv before writing out the file
        """
        csv_fieldnames = [TS_COL_NAME] + self.selected_sensors

        def row_factory() -> RowType:
            return {name: None for name in self.selected_sensors}

        rows: dict[float, RowType] = defaultdict(row_factory)

        for sample in self.samples:
            ts_bucket: float = round(sample.timestamp, 1)
            sample_row: RowType = rows[ts_bucket]
            sample_row[sample.sensor_name] = sample.value

        with self.csv_file_path.open("w", newline="") as csv_file:
            csv_writer = csv.DictWriter(csv_file, csv_fieldnames)
            csv_writer.writeheader()

            for bucket in sorted(rows):
                row: RowType = rows[bucket]
                row[TS_COL_NAME] = bucket
                csv_writer.writerow(row)

    def __exit__(self, *args) -> None:
        self.close_all()
        self.device_manager.teardown()
        self._process_csv()

        if self.do_plot_at_end:
            plot: pg.PlotWidget = pg.plot(title=self.csv_file_path.name)
            plot.addLegend()
            data: DataFrame = read_csv(self.csv_file_path)
            data_x = data[TS_COL_NAME]

            for i, name in enumerate(self.selected_sensors):
                data_y = data[name]
                plot.plot(
                    data_x,
                    data_y,
                    pen=(i, len(self.selected_sensors)),
                    name=name,
                )

            plot.show()
            self.qapp.exec()


@dataclass(frozen=True)
class Sample:
    sensor_id: int
    sensor_name: str
    timestamp: float
    value: int
