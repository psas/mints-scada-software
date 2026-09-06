import logging
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QWidget,
)

from mints_backend.script_runner import ScriptRunner

logger = logging.getLogger(__name__)


class ScriptControls(QWidget):
    def __init__(self, runner: ScriptRunner):
        super().__init__()
        layout = QHBoxLayout()
        self.runner = runner
        self.active_file = Path()
        info_box = InfoBox()
        play_btn = PlayButton()
        stop_btn = StopButton()

        play_btn.clicked.connect(self.play)
        stop_btn.clicked.connect(self.stop)

        self.set_text = info_box.setText

        layout.addWidget(info_box, 1)
        layout.addWidget(play_btn, 0)
        layout.addWidget(stop_btn, 0)
        layout.setContentsMargins(11, 5, 11, 5)

        self.setLayout(layout)
        self.setMaximumHeight(64)

    @Slot(Path)
    def set_active_file(self, path: Path):
        self.active_file = path
        self.set_text(str(path.name))

    @Slot()
    def unset_active_file(self):
        self.active_file = Path()
        self.set_text("")

    def play(self):
        if self.active_file.is_dir():
            logger.info("Unable to run - No file open")
            return
        with Path.open(self.active_file, "r") as file:
            self.runner.run(file.read(), self.active_file.name)

    def stop(self):
        self.runner.stop()


class InfoBox(QLabel):
    def __init__(self):
        super().__init__()


class PlayButton(QPushButton):
    def __init__(self):
        super().__init__()
        pixmapi = QStyle.StandardPixmap.SP_MediaPlay
        icon: QIcon = self.style().standardIcon(pixmapi)
        self.setMinimumWidth(64)
        self.setIcon(icon)


class StopButton(QPushButton):
    def __init__(self):
        super().__init__()
        pixmapi = QStyle.StandardPixmap.SP_MediaStop
        icon: QIcon = self.style().standardIcon(pixmapi)
        self.setMinimumWidth(64)
        self.setIcon(icon)
