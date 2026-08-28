from time import perf_counter

import numpy as np
from pyqtgraph.graphicsItems.PlotDataItem import PlotDataItem
from pyqtgraph.graphicsItems.PlotItem import PlotItem

from mints_backend.device_manager import UPDATE_PERIOD, Sensor


class SensorPlot:
    chunk_size = 100
    max_chunks = 10

    def __init__(
        self, sensor: Sensor, plot: PlotItem, update_period: float = UPDATE_PERIOD
    ):
        super().__init__()
        self.start_time: float = perf_counter()
        self.plot: PlotItem = plot
        self.plot.setTitle(sensor.name)
        self.plot.setExportMode(export=True)
        self.plot.setXRange(-10, 0)
        self.plot.setYRange(-100, 100)
        self.sensor: Sensor = sensor
        self.curves: list[PlotDataItem] = []
        self.data: np.ndarray = np.empty((self.chunk_size + 1, 2))
        self.ptr: int = 0

        self.sensor.subscribe(self.update_plot_data, send_period=update_period)

    def update_plot_data(self, val: int):
        now: float = perf_counter()

        for curve in self.curves:
            left_shifted_x = -(now - self.start_time)
            curve.setPos(left_shifted_x, 0)

        i: int = self.ptr % self.chunk_size

        if i == 0:
            new_curve: PlotDataItem = self.plot.plot()
            self.curves.append(new_curve)
            last = self.data[-1]
            self.data = np.empty((self.chunk_size + 1, 2))
            self.data[0] = last
            while len(self.curves) > self.max_chunks:
                first_curve = self.curves.pop(0)
                self.plot.removeItem(first_curve)
        else:
            new_curve = self.curves[-1]

        self.data[i + 1, 0] = now - self.start_time
        self.data[i + 1, 1] = val
        new_curve.setData(x=self.data[: i + 2, 0], y=self.data[: i + 2, 1])
        self.ptr += 1
