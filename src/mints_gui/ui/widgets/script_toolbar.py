import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QWidget,
)

from mints_gui.ui.widgets.menubar import MenuEntry

logger = logging.getLogger(__name__)

TOOLBAR_SIDE_WIDTH = 300
BUTTON_WIDTH = 64


class ScriptToolbar(QWidget):
    def __init__(
        self, run_script: Callable, runner_stop: Callable, add_to_menu: Callable
    ):
        super().__init__()
        layout = QHBoxLayout()
        self.active_file = Path()
        self.run_script = run_script
        self.stop_running_script = runner_stop
        self.add_to_menu = add_to_menu

        self.info_box = InfoBox()
        self.controls = ScriptControls()

        layout.addWidget(self.controls, 0)
        layout.addWidget(self.info_box, 1)

        layout.setContentsMargins(11, 5, 11, 5)

        self.setLayout(layout)
        self.setMaximumHeight(64)

        self.controls.play_btn.clicked.connect(self.play)
        self.controls.stop_btn.clicked.connect(self.stop)

        self.setup_menu_entries()

    @Slot(Path)
    def set_active_file(self, path: Path):
        self.active_file = path
        self.info_box.set_filename(str(path.name))

    @Slot()
    def on_new_file(self):
        self.unset_active_file()
        self.info_box.set_file_modified(False)

    def unset_active_file(self):
        self.active_file = Path()
        self.info_box.set_filename("")

    def play(self):
        self.run_script()

    def stop(self):
        self.stop_running_script()

    def show_running_label(self):
        self.controls.running_label.setText("Running")

    def hide_running_label(self):
        self.controls.running_label.setText("")

    def setup_menu_entries(self):
        for entry in [
            MenuEntry(
                menu="Run",
                desc="Run Script",
                callback=self.play,
                shortcut="Ctrl+r",
            ),
            MenuEntry(
                menu="Run",
                desc="Stop Script",
                callback=self.stop,
                shortcut="Ctrl+shift+r",
            ),
        ]:
            self.add_to_menu(entry)


class InfoBox(QWidget):
    def __init__(self):
        super().__init__()
        self.filename = QLabel()
        self.filename.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.changes_saved = QLabel()
        self.changes_saved.setStyleSheet("font-style: italic; color: yellow;")
        self.changes_saved.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.changes_saved.setFixedWidth(TOOLBAR_SIDE_WIDTH)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(self.filename, 1)
        layout.addWidget(self.changes_saved, 0)

        self.setLayout(layout)

    def set_filename(self, filename: str) -> None:
        self.filename.setText(filename)

    @Slot()
    def on_file_load(self):
        self.set_file_modified(False)

    @Slot()
    def on_file_saved(self):
        self.set_file_modified(False)

    @Slot(bool)
    def on_file_changed(self, is_modified: bool):
        self.set_file_modified(is_modified)

    def set_file_modified(self, file_modified: bool) -> None:
        text = "" if not file_modified else "File modified since last save"
        self.changes_saved.setText(text)


class ScriptControls(QWidget):
    def __init__(self):
        super().__init__()
        self.running_label = RunningLabel()
        self.setFixedWidth(TOOLBAR_SIDE_WIDTH)
        self.play_btn = PlayButton()
        self.stop_btn = StopButton()

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(self.play_btn, 0)
        layout.addWidget(self.stop_btn, 0)
        layout.addWidget(self.running_label, 1)

        self.setLayout(layout)


class PlayButton(QPushButton):
    def __init__(self):
        super().__init__()
        pixmapi = QStyle.StandardPixmap.SP_MediaPlay
        icon: QIcon = self.style().standardIcon(pixmapi)
        self.setFixedWidth(BUTTON_WIDTH)
        self.setIcon(icon)


class StopButton(QPushButton):
    def __init__(self):
        super().__init__()
        pixmapi = QStyle.StandardPixmap.SP_MediaStop
        icon: QIcon = self.style().standardIcon(pixmapi)
        self.setFixedWidth(BUTTON_WIDTH)
        self.setIcon(icon)


class RunningLabel(QLabel):
    def __init__(self):
        super().__init__()
        self.setFixedWidth(TOOLBAR_SIDE_WIDTH - (BUTTON_WIDTH * 2))
        self.setStyleSheet("font-weight: bold; margin-left: 2px; color: teal;")
