from pathlib import Path

from PySide6.QtGui import QIcon, QTextBlock
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QWidget,
)

from mints_backend.script_runner import ScriptRunner


class ScriptControls(QWidget):
    def __init__(self, runner: ScriptRunner):
        super().__init__()
        layout = QHBoxLayout()
        self.runner = runner
        self.active_file = ""
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

    def set_active_file(self, path: Path):
        self.active_file = path
        self.set_text(str(path.name))

    def play(self):
        self.runner.try_run(self.active_file)

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
