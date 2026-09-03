from math import ceil, sqrt

from pyqtgraph.dockarea.Dock import Dock
from pyqtgraph.dockarea.DockArea import DockArea
from PySide6.QtWidgets import QWidget

from mints_backend.device_manager import DeviceManager, Sensor
from mints_gui.ui.widgets.device_tree import DeviceParameterTree
from mints_gui.ui.widgets.sensor_plot import SensorPlot


class DevicePage(DockArea):
    def __init__(
        self, device_manager: DeviceManager, log_widget: QWidget, add_to_menu: Callable
    ):
        super().__init__()
        self.device_manager = device_manager

        self.populate_plot_area()

        tree_dock = Dock(
            "Device Tree",
            size=(175, 200),
        )
        log_dock = Dock("Log", size=(175, 50))

        self.addDock(tree_dock, "left")
        self.addDock(log_dock, "bottom", tree_dock)

        tree = DeviceParameterTree(device_manager)
        tree_dock.addWidget(tree)
        log_dock.addWidget(log_widget)

        add_to_menu(
            menu="View",
            desc="Revert Devices to Default Layout",
            callback=self.restore_default_script_page_state,
            shortcut=None,
        )

        self.default_area_state = self.saveState()

    def restore_default_script_page_state(self) -> None:
        self.restoreState(self.default_area_state)

    def populate_plot_area(self) -> None:
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

            self.addDock(next_dock, pos, relativeTo=relative_dock)

            prev_dock = next_dock
