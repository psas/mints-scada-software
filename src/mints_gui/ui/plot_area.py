from math import ceil, sqrt

from pyqtgraph import GraphicsLayoutWidget

from mints_backend.device_manager import Output, Sensor
from mints_gui.ui.widgets.sensor_plot import SensorPlot


class PlotLayout(GraphicsLayoutWidget):
    def __init__(self, device_registry: dict):
        super().__init__()
        self._sensors: dict[int, Sensor] = {}
        self.plots: list[SensorPlot] = []

        for id, device in device_registry.items():
            match device:
                case Sensor():
                    self._sensors[id] = device
                case Output():
                    pass

        self.num_graphs = len(self._sensors)
        cols = ceil(sqrt(self.num_graphs))

        for i, sensor in enumerate(self._sensors.values()):
            if i % cols == 0:
                self.nextRow()
            self.plots.append(SensorPlot(sensor, self.addPlot(), update_period=0.1))
