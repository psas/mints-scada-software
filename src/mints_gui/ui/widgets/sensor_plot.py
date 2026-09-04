from time import perf_counter

import numpy as np
from pyqtgraph import PlotWidget
from pyqtgraph.graphicsItems.PlotDataItem import PlotDataItem
from pyqtgraph.graphicsItems.PlotItem import PlotItem

from mints_backend.devices import UPDATE_PERIOD, Sensor


class SensorPlot(PlotWidget):
    chunk_size = 100
    max_chunks = 10

    def __init__(self, sensor: Sensor, update_period: float = UPDATE_PERIOD):
        super().__init__()
        self.start_time: float = perf_counter()
        self.plot_item: PlotItem = self.plot()
        self.sensor: Sensor = sensor
        self.curves: list[PlotDataItem] = []
        self.data: np.ndarray = np.empty((self.chunk_size + 1, 2))
        self.ptr: int = 0

        self.plot_item.setExportMode(export=True)
        self.setXRange(-10, 0)
        self.setYRange(-100, 100)

        self.sensor.subscribe(self.update_plot, send_period=update_period)

    def update_plot(self, val: int):
        now: float = perf_counter()

        self._shift_all_curves_left(now)

        i: int = self.ptr % self.chunk_size

        if i == 0:
            new_curve = self._get_new_curve()
            self._reset_data_preserve_last()
            self._trim_oldest_curves()
        else:
            new_curve = self.curves[-1]

        # i + 1 because we preserve the last point
        self.data[i + 1, 0] = now - self.start_time
        self.data[i + 1, 1] = val

        new_curve.setData(x=self.data[: i + 2, 0], y=self.data[: i + 2, 1])

        self.ptr += 1

    def _shift_all_curves_left(self, curr_time: float):
        for curve in self.curves:
            left_shifted_x = -(curr_time - self.start_time)
            curve.setPos(left_shifted_x, 0)

    def _get_new_curve(self) -> PlotDataItem:
        new_curve: PlotDataItem = self.plot()
        self.curves.append(new_curve)
        return new_curve

    def _reset_data_preserve_last(self) -> None:
        last = self.data[-1]
        self.data = np.empty((self.chunk_size + 1, 2))
        self.data[0] = last

    def _trim_oldest_curves(self) -> None:
        while len(self.curves) > self.max_chunks:
            oldest_curve = self.curves.pop(0)
            self.removeItem(oldest_curve)
