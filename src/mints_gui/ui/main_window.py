from logging import getLogger

import numpy as np
import pyqtgraph as pg
from pyqtgraph.dockarea.Dock import Dock
from pyqtgraph.dockarea.DockArea import DockArea
from PySide6.QtWidgets import QMainWindow, QSizePolicy, QWidget

from mints_backend.device_manager import DeviceManager
from mints_gui.ui.device_tree import DeviceParameterTree

global data
data = np.zeros(100)

log = getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(
        self,
        log_widget: QWidget,
        console_widget: QWidget | None,
        device_manager: DeviceManager,
    ):
        super().__init__()
        log.debug("Initializing main window")

        self.resize(1280, 720)
        self.setWindowTitle("MinTS")

        self.area = DockArea()
        self.setCentralWidget(self.area)

        log_dock = Dock("Log", size=(200, 25), closable=True)
        tree_dock = Dock("Device Tree", size=(100, 100))
        graph_dock = Dock("Graph", size=(500, 100))

        self.area.addDock(tree_dock, "top")
        self.area.addDock(graph_dock, "right", tree_dock)
        self.area.addDock(log_dock, "bottom")
        if console_widget:
            console_widget.localNamespace.update({"window": self})  # pyright: ignore[reportAttributeAccessIssue]
            console_dock = Dock("Console", size=(200, 25), closable=True)
            self.area.addDock(console_dock, "right", log_dock)
            console_dock.addWidget(console_widget)

        tree = DeviceParameterTree(device_manager)
        tree_dock.addWidget(tree)
        log_dock.addWidget(log_widget)
