from PyQt5.QtWidgets import QWidget, QHBoxLayout, QPushButton
import matplotlib
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt5.QtCore import QTimer
import time
import numpy as np
from matplotlib.animation import FuncAnimation
from nexus import GenericSensor

class GraphTab(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = QHBoxLayout()
        self.setLayout(self.layout)

        self.duration = 60

        self.x = [0]
        self.y = [0]
        
        self.sensors: list[GenericSensor]= []

        self.fig = Figure(figsize=(5, 4), dpi=100)
        self.axes = self.fig.add_subplot(111)
        self.canvas = FigureCanvasQTAgg(self.fig)

        col = 0x43/256
        bkg = (col, col, col)
        fgc = "#f4f4f4"
        self.fig.set_facecolor(bkg)
        self.axes.set_facecolor(bkg)
        self.axes.spines['bottom'].set_color(fgc)
        self.axes.spines['top'].set_color(fgc) 
        self.axes.spines['right'].set_color(fgc)
        self.axes.spines['left'].set_color(fgc)
        self.axes.tick_params(axis='x', colors=fgc)
        self.axes.tick_params(axis='y', colors=fgc)
        self.axes.yaxis.label.set_color(fgc)
        self.axes.xaxis.label.set_color(fgc)
        self.axes.title.set_color(fgc)

        self.lines = []

        self.axes.set_xlim(0, 100)
        self.axes.set_ylim(0, 2)

        self.layout.addWidget(self.canvas)

        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.update)
        self.timer.start()

    def update(self):
        ymin = 0
        ymax = 0

        start = time.time()
        thresh = start - self.duration
        for i in range(len(self.sensors)):
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
        
        self.axes.set_ylim(ymin-0.1, ymax+0.1)
        self.axes.set_xlim(-60, 0)

        self.canvas.draw_idle()
        print(f"{(time.time() - start)*1000:.2f}")

    def addSensor(self, sensor: GenericSensor):
        self.sensors.append(sensor)
        self.lines.append(self.axes.plot([None], [None])[0])

