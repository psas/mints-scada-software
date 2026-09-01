from logging import getLogger
from math import ceil, sqrt

from pyqtgraph.dockarea.Dock import Dock
from pyqtgraph.dockarea.DockArea import DockArea
from PySide6.QtWidgets import (
    QMainWindow,
    QMenu,
    QMenuBar,
    QTabWidget,
    QWidget,
)

from mints_backend.device_manager import DeviceManager, Sensor
from mints_gui.ui.device_tree import DeviceParameterTree
from mints_gui.ui.widgets.sensor_plot import SensorPlot

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
        self.device_manager = device_manager
        self.default_width = 1280
        self.default_height = 720

        self.resize(self.default_width, self.default_height)
        self.setWindowTitle("MinTS")

        self.menu = QMenuBar()
        self.area = DockArea()
        self.view_menu = QMenu("View")
        self.view_menu.addAction(
            "Revert devices to default layout", self.restore_default_area_state
        )
        self.menu.addMenu(self.view_menu)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.area, "Devices")
        self.setMenuBar(self.menu)
        self.setCentralWidget(self.tabs)

        self.populate_plot_area()

        tree_dock = Dock(
            "Device Tree",
            size=((1 / 6) * self.default_width, (2 / 3) * self.default_height),
        )
        log_dock = Dock(
            "Log",
            size=((1 / 6) * self.default_width, (1 / 3) * self.default_height),
        )

        self.area.addDock(tree_dock, "left")
        self.area.addDock(log_dock, "bottom", tree_dock)

        tree = DeviceParameterTree(device_manager)
        tree_dock.addWidget(tree)
        log_dock.addWidget(log_widget)

        if console_widget:
            console_widget.localNamespace.update(
                {"window": self, "devicetree": tree, "plots": self.plot_area}
            )
            console_dock = Dock("Console", size=(200, 25), closable=True)
            self.area.addDock(console_dock, "bottom")
            console_dock.addWidget(console_widget)

        self.default_area_state = self.area.saveState()

    def restore_default_area_state(self):
        self.area.restoreState(self.default_area_state)

    def populate_plot_area(self):
        sensors: list[Sensor] = [
            device
            for device in self.device_manager.device_registry.values()
            if isinstance(device, Sensor)
        ]

        cols: int = ceil(sqrt(len(sensors)))

        prev_dock: Dock | None = None
        should_drop_row: bool = False

        for i, sensor in enumerate(sensors):
            next_plot = SensorPlot(sensor, update_period=0.1)

            next_dock = Dock(sensor.name, size=(150, 150), autoOrientation=False)
            next_dock.setOrientation(o="vertical", force=True)
            next_dock.addWidget(next_plot)

            if i != 0:
                should_drop_row = i % cols == 0

            pos: str = "bottom" if should_drop_row else "right"
            relative_dock: Dock | None = None if should_drop_row else prev_dock

            self.area.addDock(next_dock, pos, relativeTo=relative_dock)

            prev_dock = next_dock
