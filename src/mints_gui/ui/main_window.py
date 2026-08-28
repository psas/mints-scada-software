from logging import getLogger

from pyqtgraph.dockarea.Dock import Dock
from pyqtgraph.dockarea.DockArea import DockArea
from PySide6.QtWidgets import QMainWindow, QWidget

from mints_backend.device_manager import DeviceManager
from mints_gui.ui.device_tree import DeviceParameterTree
from mints_gui.ui.widgets.plot_layout import PlotLayout

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
        plot_area_dock = Dock("Plot", size=(500, 100))
        plot_layout = PlotLayout(device_manager.device_registry)
        plot_area_dock.addWidget(plot_layout)

        self.area.addDock(tree_dock, "top")
        self.area.addDock(plot_area_dock, "right", tree_dock)
        self.area.addDock(log_dock, "bottom")

        if console_widget:
            console_widget.localNamespace.update({"window": self})
            console_dock = Dock("Console", size=(200, 25), closable=True)
            self.area.addDock(console_dock, "right", log_dock)
            console_dock.addWidget(console_widget)

        tree = DeviceParameterTree(device_manager)
        tree_dock.addWidget(tree)
        log_dock.addWidget(log_widget)
