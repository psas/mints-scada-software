from logging import getLogger

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QTabWidget

from mints_backend.device_manager import DeviceManager
from mints_backend.script_runner import ScriptRunner
from mints_gui.logging import SignalHandler
from mints_gui.ui.device_page import DevicePage
from mints_gui.ui.script_page import ScriptPage
from mints_gui.ui.widgets.menubar import MenuBar

log = getLogger(__name__)


class MainWindow(QMainWindow):
    default_width = 1280
    default_height = 720

    def __init__(
        self,
        log_signal: SignalHandler,
        device_manager: DeviceManager,
        runner: ScriptRunner,
    ):
        super().__init__()
        log.debug("Initializing main window")
        menu = MenuBar()
        device_page = DevicePage(device_manager, log_signal, menu.add_to_menu)
        self.script_page = ScriptPage(log_signal, runner, menu.add_to_menu)

        tabs = QTabWidget()
        tabs.addTab(device_page, "Devices")
        tabs.addTab(self.script_page, "Scripting")

        self.setMenuBar(menu)
        self.setCentralWidget(tabs)
        self.resize(self.default_width, self.default_height)
        self.setWindowTitle("MinTS")

    def closeEvent(self, event: QCloseEvent):
        """
        Check for unsaved changes when the user tries to exit
        """
        if (
            self.script_page.script_widget.script_editor.file_modified
            and not self.script_page.script_widget.script_editor.confirm_discard_changes()
        ):
            event.ignore()
            return

        event.accept()
