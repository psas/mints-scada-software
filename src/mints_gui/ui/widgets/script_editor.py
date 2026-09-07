import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox, QTextEdit

from mints_gui.ui.widgets.menubar import MenuEntry

logger = logging.getLogger(__name__)

NEW_FILE_TEXT = "#! mints\nfrom mints_backend.dsl import Mints\n\n\nmints = Mints()"


class ScriptEditor(QTextEdit):
    sig_file_saved = Signal(Path)
    sig_file_opened = Signal(Path)
    sig_file_new = Signal()
    sig_file_changed = Signal(bool)

    def __init__(self, runner_run_fn: Callable, add_to_menu: Callable):
        super().__init__()
        self._run = runner_run_fn
        self.setUndoRedoEnabled(True)
        self.active_file: Path = Path()
        self.setup_menu_actions(add_to_menu)
        self.setPlainText(NEW_FILE_TEXT)
        self.file_modified = False

        self.textChanged.connect(self.check_for_file_modified)

    def run_script(self):
        self._run(self.toPlainText())

    @Slot(Path)
    def set_active_file(self, file_path: Path):
        self.active_file = file_path
        with Path.open(file_path) as file:
            self.setPlainText(file.read())

    def new_file(self):
        if self.file_modified and not self.confirm_discard_changes():
            return

        self.active_file = Path()
        self.setPlainText(NEW_FILE_TEXT)
        self.sig_file_new.emit()

    def open_file(self):
        filename, _filter = QFileDialog.getOpenFileName(
            caption="Open File", dir=str(self.active_file.parent)
        )
        if not filename:
            return
        file_path = Path(filename)
        self.sig_file_opened.emit(file_path)

    def save_file(self):
        if not self.active_file.name:
            self.save_file_as()
        else:
            with Path.open(self.active_file, "w") as file:
                file.write(self.toPlainText())
            self.sig_file_saved.emit(self.active_file)
            logger.info("Saved %s", str(self.active_file))

    def save_file_as(self):
        filename, _filter = QFileDialog.getSaveFileName(
            caption="Save File As",
            dir=str(self.active_file.parent),
            filter="*.py",
            selectedFilter="*.py",
        )
        if not filename:
            return
        file_path = Path(filename).with_suffix(".py")
        with Path.open(file_path, "w") as file:
            file.write(self.toPlainText())
        self.sig_file_saved.emit(file_path)
        logger.info("Saved %s", str(file_path))

    def check_for_file_modified(self) -> None:
        if self.active_file.is_dir():
            is_modified = self.toPlainText() != NEW_FILE_TEXT
        else:
            with Path.open(self.active_file) as file:
                is_modified = self.toPlainText() != file.read()

        self.sig_file_changed.emit(is_modified)
        self.file_modified = is_modified

    def confirm_discard_changes(self) -> bool:
        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            "The current file has unsaved changes. Do you want to save before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )

        if reply == QMessageBox.StandardButton.Save:
            self.save_file()
            return True
        return reply == QMessageBox.StandardButton.Discard

    def setup_menu_actions(self, add_to_menu: Callable):
        for entry in [
            MenuEntry(
                menu="File",
                desc="New",
                callback=self.new_file,
                shortcut="Ctrl+n",
            ),
            MenuEntry(
                menu="File",
                desc="Save",
                callback=self.save_file,
                shortcut="Ctrl+s",
            ),
            MenuEntry(
                menu="File",
                desc="Save as",
                callback=self.save_file_as,
                shortcut="Ctrl+shift+s",
            ),
            MenuEntry(
                menu="File",
                desc="Open file",
                callback=self.open_file,
                shortcut="Ctrl+o",
            ),
            MenuEntry(
                menu="Edit",
                desc="Cut",
                callback=self.cut,
                shortcut="Ctrl+x",
            ),
            MenuEntry(
                menu="Edit",
                desc="Copy",
                callback=self.copy,
                shortcut="Ctrl+c",
            ),
            MenuEntry(
                menu="Edit",
                desc="Paste",
                callback=self.paste,
                shortcut="Ctrl+v",
            ),
            MenuEntry(
                menu="Edit",
                desc="Undo",
                callback=self.undo,
                shortcut="Ctrl+z",
            ),
            MenuEntry(
                menu="Edit",
                desc="Redo",
                callback=self.redo,
                shortcut="Ctrl+y",
            ),
        ]:
            add_to_menu(entry)
