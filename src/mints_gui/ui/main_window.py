from logging import getLogger

from PySide6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QWidget,
)

from mints_backend.device_manager import DeviceManager
from mints_gui.ui.device_page import DevicePage
from mints_gui.ui.script_page import ScriptPage
from mints_gui.ui.widgets.menubar import MenuBar

log = getLogger(__name__)


class MainWindow(QMainWindow):
    default_width = 1280
    default_height = 720

    def __init__(
        self,
        log_widget: QWidget,
        device_manager: DeviceManager,
    ):
        super().__init__()
        log.debug("Initializing main window")
        self.menu = MenuBar()
        self.device_manager = device_manager
        self.device_page = DevicePage(device_manager, log_widget, self.menu.add_to_menu)
        self.script_page = ScriptPage(self.menu.add_to_menu)
        self.tabs = QTabWidget()

        self.tabs.addTab(self.device_page, "Devices")
        self.tabs.addTab(self.script_page, "Scripting")
        self.setCentralWidget(self.tabs)
        self.setMenuBar(self.menu)
        self.resize(self.default_width, self.default_height)
        self.setWindowTitle("MinTS")
