from PyQt5.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QCheckBox,
    QSpinBox,
    QLabel,
)
import matplotlib
import matplotlib.lines
import matplotlib.pyplot
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg  # type: ignore
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
import time
import numpy as np
from nexus import GenericSensor
import logging

log = logging.getLogger("Graph")


class GraphView(QWidget):
    durationChanged = pyqtSignal(int)

    FOREGROUND_COLOR = "#f4f4f4"
    BACKGROUND_COLOR = "#19232d"
    LEGEND_COLOR = "#353535"

    def __init__(self):
        super().__init__()
        self.layout = QHBoxLayout()
        self.setLayout(self.layout)

        self.duration = 60
        self.x = [0]
        self.y = [0]

        self.sensors: list[object] = []

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

        self.lines: list[matplotlib.lines.Line2D] = []

        self.axes.set_xlim(0, 100)
        self.axes.set_ylim(0, 2)

        self.layout.addWidget(self.canvas, 999)

        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._update)
        self.timer.start()

        self.controlLayout = QVBoxLayout()
        self.layout.addLayout(self.controlLayout, 0)
        self.controlLayout.setAlignment(Qt.AlignTop)

        self.durlayout = QHBoxLayout()

        self.durlabel = QLabel("Graph Duration:")
        self.durlayout.addWidget(self.durlabel)

        # Create spin box
        self.spin_box = QSpinBox()
        self.spin_box.setValue(self.duration)
        self.spin_box.setRange(1, 9999)
        self.spin_box.setSuffix("s")
        self.spin_box.valueChanged.connect(
            self._updateSpin
        )  # Connect valueChanged signal to function

        # Add spin box to layout
        self.durlayout.addWidget(self.spin_box)
        self.controlLayout.addLayout(self.durlayout)

        self.checkboxes: list[QCheckBox] = []

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

    def _updateSpin(self):
        self.duration = self.spin_box.value()
        self.durationChanged.emit(int(self.duration))
        self._update()

    def _update(self):
        ymin = 0
        ymax = 0

        start = time.time()
        thresh = start - self.duration
        count = 0

        if hasattr(self, "legend") and self.legend is not None:
            try:
                self.legend.remove()
            except Exception:
                pass
            self.legend = None

        for i in range(len(self.sensors)):
            try:
                if i >= len(self.checkboxes) or i >= len(self.lines):
                    continue

                if self.checkboxes[i].isChecked():
                    hist = self._extract_history(self.sensors[i])
                    if hist is not None:
                        vals = hist[:, hist[0] > thresh]
                        x = vals[0] - start
                        y = vals[1]
                        if len(y) > 0:
                            self.lines[i].set_xdata(x)
                            self.lines[i].set_ydata(y)
                            ymin = min(np.min(vals[1]), ymin)
                            ymax = max(np.max(vals[1]), ymax)
                            self.axes.draw_artist(self.lines[i])
                            self.lines[i].set_label(self._display_label(self.sensors[i]))
                            count += 1
                            continue

            except Exception:
                log.exception(
                    "Graph update failed for sensor %s",
                    self._runtime_id(self.sensors[i]),
                )

            self.lines[i].set_xdata([None])
            self.lines[i].set_ydata([None])
            self.lines[i].set_label(None)

        self.axes.set_ylim(ymin - 0.1, ymax + 0.1)
        self.axes.set_xlim(-self.duration, 0)
        if count > 0:
            self.legend = self.axes.legend(loc="upper left")
            self.legend.get_frame().set_facecolor(self.LEGEND_COLOR)
            self.legend.get_frame().set_edgecolor(self.FOREGROUND_COLOR)
            for text in self.legend.get_texts():
                text.set_color(self.FOREGROUND_COLOR)

        self.canvas.draw_idle()
        # print(f"{(time.time() - start)*1000:.2f}")

    def addSensor(self, sensor: GenericSensor, graphed=True):
        self.sensors.append(sensor)

        label = self._display_label(sensor)
        self.lines.append(self.axes.plot([None], [None], label=label)[0])

        cb = QCheckBox(label)
        self.controlLayout.addWidget(cb)
        self.checkboxes.append(cb)
        cb.setChecked(graphed)
        return True

    # Functions for use in scripts
    def setDuration(self, duration: int):
        """Sets the duration of the graph"""
        self.duration = duration
        self.durationChanged.emit(int(self.duration))
        self._update()

    def enableChannel(self, channel: str, state: bool = True) -> bool:
        """Set if a channel is enabled in the graph.

        * channel is the device id of the channel
        * state is a boolean if the channel should be enabled or not, defaults to true
        * Returns if the channel was changed
        """
        for i in range(len(self.sensors)):
            if self._runtime_id(self.sensors[i]) == channel:
                self.checkboxes[i].setChecked(state)
                return True
        return False
