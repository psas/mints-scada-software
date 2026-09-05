from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QTextEdit

from mints_backend.script_runner import ScriptRunner


class ScriptEditor(QTextEdit):
    def __init__(self, runner: ScriptRunner):
        super().__init__()

    @Slot(Path)
    def set_active_file(self, file_path: Path):
        with Path.open(file_path) as file:
            self.setPlainText(file.read())
