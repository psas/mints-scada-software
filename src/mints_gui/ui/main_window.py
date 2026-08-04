from logging import getLogger

import numpy as np
import pyqtgraph as pg
from pyqtgraph.dockarea.Dock import Dock
from pyqtgraph.dockarea.DockArea import DockArea
from PySide6.QtWidgets import QMainWindow, QSizePolicy, QWidget

global data
data = np.zeros(100)

log = getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, log_widget: QWidget, console_widget: QWidget | None):
        super().__init__()
        log.debug("Initializing main window")

        self.resize(1280, 720)
        self.setWindowTitle("MinTS")

        self.area = DockArea()
        self.setCentralWidget(self.area)

        d1 = Dock("Log", size=(500, 100), closable=True)
        d3 = Dock("Graph 1", size=(500, 200))
        d4 = Dock("Graph 2", size=(500, 200))
        d5 = Dock("Graph 3", size=(500, 200))
        d6 = Dock("Graph 4", size=(500, 200))
        d7 = Dock("Buttons", size=(200, 100))

        self.area.addDock(d1, "bottom")
        self.area.addDock(d3, "top")
        self.area.addDock(d7, "left", d3)
        self.area.addDock(d4, "right", d3)
        self.area.addDock(d5, "bottom", d3)
        self.area.addDock(d6, "bottom", d4)

        if console_widget:
            console_widget.localNamespace.update({"window": self})  # pyright: ignore[reportAttributeAccessIssue]
            d2 = Dock("Console", size=(500, 100), closable=True)
            self.area.addDock(d2, "right", d1)
            d2.addWidget(console_widget)

        d1.addWidget(log_widget)

        w3 = pg.PlotWidget()
        self.plot0 = w3.plot(np.random.normal(size=100))
        d3.addWidget(w3)

        w4 = pg.PlotWidget()
        self.plot1 = w4.plot(np.random.normal(size=100))
        d4.addWidget(w4)

        w5 = pg.PlotWidget()
        self.plot2 = w5.plot(np.random.normal(size=100))
        d5.addWidget(w5)

        w6 = pg.PlotWidget()
        self.plot3 = w6.plot(np.random.normal(size=100))
        d6.addWidget(w6)

        w7 = pg.FeedbackButton("Button 1")
        w8 = pg.FeedbackButton("Button 2")
        w9 = pg.FeedbackButton("Button 3")
        w10 = pg.FeedbackButton("Button 4")

        for btn in (w7, w8, w9, w10):
            btn.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            d7.addWidget(btn)

    def update_graph(self):
        global data
        data = np.append(data, np.random.default_rng().standard_normal())
        data = data[-100:]
        self.plot0.setData(data)
        self.plot1.setData(data)
        self.plot2.setData(data)
        self.plot3.setData(data)
