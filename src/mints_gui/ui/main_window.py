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
    def __init__(
        self,
        log_widget: QWidget,
        device_manager: DeviceManager,
    ):
        super().__init__()
        log.debug("Initializing main window")
        self.device_manager = device_manager
        self.default_width = 1280
        self.default_height = 720
        self.menu = MenuBar(
            self.restore_default_script_page_state,
        )
        self.device_page = DevicePage(
            device_manager=device_manager,
            log_widget=log_widget,
        )
        self.script_page = ScriptPage()
        self.tabs = QTabWidget()
        self.tabs.addTab(self.device_page, "Devices")
        self.tabs.addTab(self.script_page, "Scripting")

        self.setCentralWidget(self.tabs)
        self.setMenuBar(self.menu)
        self.resize(self.default_width, self.default_height)
        self.setWindowTitle("MinTS")

    def restore_default_script_page_state(self):
        self.device_page.restoreState(self.device_page.default_area_state)
