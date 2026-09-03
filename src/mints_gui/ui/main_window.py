from collections.abc import Callable
from logging import getLogger
from typing import Literal

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QWidget,
)

from mints_backend.device_manager import DeviceManager
from mints_gui.ui.device_page import DevicePage
from mints_gui.ui.script_page import ScriptPage
from mints_gui.ui.widgets.menubar import MenuBar, MenuEntry, MenuTypes

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
        self.menu_entries: list[MenuEntry] = []
        self.device_page = DevicePage(device_manager, log_widget, self.add_to_menu)
        self.script_page = ScriptPage(self.add_to_menu)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.device_page, "Devices")
        self.tabs.addTab(self.script_page, "Scripting")

        self.menu = MenuBar(
            self.menu_entries,
        )

        self.setCentralWidget(self.tabs)
        self.setMenuBar(self.menu)
        self.resize(self.default_width, self.default_height)
        self.setWindowTitle("MinTS")

    def add_to_menu(
        self,
        menu: MenuTypes,
        desc: str,
        callback: Callable,
        shortcut: QKeySequence | None,
    ) -> None:
        self.menu_entries.append(
            MenuEntry(menu, desc, callback, None if shortcut is None else shortcut)
        )
