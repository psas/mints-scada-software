from PyQt5.QtWidgets import QWidget, QVBoxLayout
import matplotlib
import matplotlib.lines
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg  # type: ignore
from matplotlib.figure import Figure
from PyQt5.QtCore import QTimer, pyqtSignal
import time
import numpy as np
from nexus import GenericSensor
import logging

log = logging.getLogger("Graph")


class GraphView(QWidget):
    durationChanged = pyqtSignal(int)
    seriesChanged = pyqtSignal()

    FOREGROUND_COLOR = "#f4f4f4"
    BACKGROUND_COLOR = "#19232d"
    LEGEND_COLOR = "#353535"

    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.setLayout(self.layout)

        self.duration = 60
        self.sensors: list[object] = []
        self.lines: list[matplotlib.lines.Line2D] = []
        self._enabled_channels: dict[str, bool] = {}

        logging.getLogger("matplotlib").setLevel(logging.INFO)

        self.fig = Figure(figsize=(5, 4), dpi=100)
        self.axes = self.fig.add_subplot(111)
        self.canvas = FigureCanvasQTAgg(self.fig)

        self.fig.set_facecolor(self.BACKGROUND_COLOR)
        self.axes.set_facecolor(self.BACKGROUND_COLOR)
        self.axes.spines["bottom"].set_color(self.FOREGROUND_COLOR)
        self.axes.spines["top"].set_color(self.FOREGROUND_COLOR)
        self.axes.spines["right"].set_color(self.FOREGROUND_COLOR)
        self.axes.spines["left"].set_color(self.FOREGROUND_COLOR)
        self.axes.tick_params(axis="x", colors=self.FOREGROUND_COLOR)
        self.axes.tick_params(axis="y", colors=self.FOREGROUND_COLOR)
        self.axes.yaxis.label.set_color(self.FOREGROUND_COLOR)
        self.axes.xaxis.label.set_color(self.FOREGROUND_COLOR)
        self.axes.title.set_color(self.FOREGROUND_COLOR)
        self.axes.grid("both", "major")

        self.fig.tight_layout(pad=2)
        self.axes.set_xlim(0, 100)
        self.axes.set_ylim(0, 2)

        self.layout.addWidget(self.canvas, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._update)
        self.timer.start()

    def _display_label(self, sensor: object) -> str:
        return getattr(sensor, "display_name", getattr(sensor, "device_id", "Unknown"))

    def _runtime_id(self, sensor: object) -> str:
        return getattr(sensor, "device_id", "")

    def _extract_history(self, sensor: object):
        hist = getattr(sensor, "history", None)
        if hist is None:
            return None

        try:
            hist = np.asarray(hist)
        except Exception:
            log.exception("Failed to convert history for sensor %s", self._runtime_id(sensor))
            return None

        if hist.ndim != 2 or hist.shape[0] < 2:
            return None

        return hist

    def _is_enabled(self, sensor: object) -> bool:
        runtime_id = self._runtime_id(sensor)
        return self._enabled_channels.get(runtime_id, True)

    def _set_empty_line(self, idx: int):
        if 0 <= idx < len(self.lines):
            self.lines[idx].set_xdata([None])
            self.lines[idx].set_ydata([None])

    def _update(self):
        ymin = 0.0
        ymax = 0.0
        visible_count = 0

        start = time.time()
        thresh = start - self.duration

        for idx, sensor in enumerate(self.sensors):
            try:
                if idx >= len(self.lines):
                    continue

                if not self._is_enabled(sensor):
                    self._set_empty_line(idx)
                    continue

                hist = self._extract_history(sensor)
                if hist is None:
                    self._set_empty_line(idx)
                    continue

                vals = hist[:, hist[0] > thresh]
                if vals.shape[1] == 0:
                    self._set_empty_line(idx)
                    continue

                x = vals[0] - start
                y = vals[1]
                if len(y) == 0:
                    self._set_empty_line(idx)
                    continue

                self.lines[idx].set_xdata(x)
                self.lines[idx].set_ydata(y)
                ymin = min(float(np.min(y)), ymin)
                ymax = max(float(np.max(y)), ymax)
                visible_count += 1

            except Exception:
                log.exception(
                    "Graph update failed for sensor %s",
                    self._runtime_id(sensor),
                )
                self._set_empty_line(idx)

        if visible_count == 0:
            self.axes.set_ylim(-0.1, 0.1)
        else:
            self.axes.set_ylim(ymin - 0.1, ymax + 0.1)
        self.axes.set_xlim(-self.duration, 0)
        self.canvas.draw_idle()

    def is_channel_enabled(self, channel: str) -> bool:
        return self._enabled_channels.get(channel, True)

    def legend_entries(self) -> list[tuple[str, str, str, bool]]:
        entries = []
        for sensor, line in zip(self.sensors, self.lines):
            runtime_id = self._runtime_id(sensor)
            entries.append((
                runtime_id,
                self._display_label(sensor),
                line.get_color(),
                self.is_channel_enabled(runtime_id),
            ))
        return entries

    def add_device(self, sensor: object, graphed: bool = True) -> bool:
        runtime_id = self._runtime_id(sensor)
        if runtime_id and any(self._runtime_id(existing) == runtime_id for existing in self.sensors):
            self.enableChannel(runtime_id, graphed)
            return False

        self.sensors.append(sensor)
        label = self._display_label(sensor)
        line = self.axes.plot([None], [None], label=label)[0]
        self.lines.append(line)

        if runtime_id:
            self._enabled_channels[runtime_id] = bool(graphed)

        self.seriesChanged.emit()
        self._update()
        return True

    def addSensor(self, sensor: GenericSensor, graphed=True):
        return self.add_device(sensor, graphed)

    def remove_device(self, channel: str) -> bool:
        for idx, sensor in enumerate(self.sensors):
            if self._runtime_id(sensor) != channel:
                continue

            self.sensors.pop(idx)
            line = self.lines.pop(idx)
            try:
                line.remove()
            except Exception:
                pass
            self._enabled_channels.pop(channel, None)
            self.seriesChanged.emit()
            self._update()
            return True
        return False

    def clear_devices(self):
        self.sensors.clear()
        while self.lines:
            line = self.lines.pop()
            try:
                line.remove()
            except Exception:
                pass
        self._enabled_channels.clear()
        self.seriesChanged.emit()
        self._update()

    def set_devices(self, devices: list[object], graphed: bool = True):
        self.clear_devices()
        for device in devices:
            self.add_device(device, graphed)
        self.seriesChanged.emit()
        self._update()

    def set_duration(self, duration: int):
        self.duration = max(1, int(duration))
        self.durationChanged.emit(int(self.duration))
        self._update()

    # Functions for use in scripts
    def setDuration(self, duration: int):
        """Sets the duration of the graph"""
        self.set_duration(duration)

    def enableChannel(self, channel: str, state: bool = True) -> bool:
        """Set if a channel is enabled in the graph.

        * channel is the device id of the channel
        * state is a boolean if the channel should be enabled or not, defaults to true
        * Returns if the channel was changed
        """
        for sensor in self.sensors:
            if self._runtime_id(sensor) == channel:
                self._enabled_channels[channel] = bool(state)
                self.seriesChanged.emit()
                self._update()
                return True
        return False
