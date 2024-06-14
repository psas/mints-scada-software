from PyQt5.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QCheckBox, QSpinBox, QLabel
import matplotlib
import matplotlib.lines
import matplotlib.pyplot
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg # type: ignore
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt, QTimer
import time
import numpy as np
from nexus import GenericSensor
import logging

log = logging.getLogger("Graph")


class GraphView(QWidget):
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
        
        self.sensors: list[GenericSensor]= []

        logging.getLogger("matplotlib").setLevel(logging.INFO)

        self.fig = Figure(figsize=(5, 4), dpi=100)
        self.axes = self.fig.add_subplot(111)
        self.canvas = FigureCanvasQTAgg(self.fig)

        self.fig.set_facecolor(self.BACKGROUND_COLOR)
        self.axes.set_facecolor(self.BACKGROUND_COLOR)
        self.axes.spines['bottom'].set_color(self.FOREGROUND_COLOR)
        self.axes.spines['top'].set_color(self.FOREGROUND_COLOR) 
        self.axes.spines['right'].set_color(self.FOREGROUND_COLOR)
        self.axes.spines['left'].set_color(self.FOREGROUND_COLOR)
        self.axes.tick_params(axis='x', colors=self.FOREGROUND_COLOR)
        self.axes.tick_params(axis='y', colors=self.FOREGROUND_COLOR)
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
        self.spin_box.valueChanged.connect(self._updateSpin)  # Connect valueChanged signal to function

        # Add spin box to layout
        self.durlayout.addWidget(self.spin_box)
        self.controlLayout.addLayout(self.durlayout)

        self.checkboxes: list[QCheckBox] = []

    def _updateSpin(self):
        self.duration = self.spin_box.value()
        self._update()

    def _update(self):
        ymin = 0
        ymax = 0

        start = time.time()
        thresh = start - self.duration
        count = 0
        for i in range(len(self.sensors)):
            if self.checkboxes[i].isChecked():
                hist = self.sensors[i].history
                vals = hist[:,hist[0]>thresh]
                x = vals[0]-start
                y = vals[1]
                if len(y) > 0:
                    self.lines[i].set_xdata(x)
                    self.lines[i].set_ydata(y)
                    ymin = min(np.min(vals[1]), ymin)
                    ymax = max(np.max(vals[1]), ymax)
                    self.axes.draw_artist(self.lines[i])
                    self.lines[i].set_label(self.sensors[i].name)
                    count += 1
                    continue
            self.lines[i].set_xdata([None])
            self.lines[i].set_ydata([None])
            self.lines[i].set_label(None)

        
        self.axes.set_ylim(ymin-0.1, ymax+0.1)
        self.axes.set_xlim(-self.duration, 0)
        # self.axes.legend(loc='upper left')
        if count > 0:
            self.legend = self.axes.legend(loc='upper left')
            self.legend.get_frame().set_facecolor(self.LEGEND_COLOR)
            self.legend.get_frame().set_edgecolor(self.FOREGROUND_COLOR)
            for text in self.legend.get_texts():
                text.set_color(self.FOREGROUND_COLOR)

        self.canvas.draw_idle()
        # print(f"{(time.time() - start)*1000:.2f}")

    def addSensor(self, sensor: GenericSensor, graphed = True):
        self.sensors.append(sensor)
        self.lines.append(self.axes.plot([None], [None], label=sensor.name)[0])
        cb = QCheckBox(sensor.name)
        self.controlLayout.addWidget(cb)
        self.checkboxes.append(cb)
        cb.setChecked(graphed)

    # Functions for use in scripts
    def setDuration(self, duration: int):
        ''' Sets the duration of the graph '''
        self.duration = duration
        self._update()

    def enableChannel(self, channel: str, state: bool = True) -> bool:
        ''' Set if a channel is enabled in the graph.
        
        * channel is the string name of the channel
        * state is a boolean if the channel should be enabled or not, defaults to true
        * Returns if the channel was changed '''
        for i in range(len(self.sensors)):
            if self.sensors[i].name == channel:
                self.checkboxes[i].setChecked(state)
                return True
        return False