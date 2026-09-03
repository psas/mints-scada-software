from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, Signal, Slot
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QFileIconProvider,
    QFileSystemModel,
    QSizePolicy,
    QTreeView,
)

from mints_gui.ui.widgets.menubar import MenuEntry


class FileExplorerWidget(QTreeView):
    sig_file_selected = Signal(Path)

    def __init__(self, add_to_menu: Callable):
        super().__init__()
        self.file_model = QFileSystemModel()
        self.icon_provider = QFileIconProvider()
        self.root_path: str = QDir.currentPath()

        self.file_model.setRootPath(self.root_path)
        self.file_model.setIconProvider(self.icon_provider)
        self.file_model.setReadOnly(True)

        self.setModel(self.file_model)
        root_index: QModelIndex = self.file_model.index(self.root_path)
        if root_index.isValid():
            self.setRootIndex(root_index)
        self.setAnimated(True)
        self.setSortingEnabled(False)
        self.setHeaderHidden(True)
        for col in range(1, self.file_model.columnCount()):
            self.hideColumn(col)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        self.doubleClicked.connect(self.on_file_selected)

        add_to_menu(
            MenuEntry(
                menu="File",
                desc="Open Folder",
                callback=self.set_root_from_dialog,
                shortcut=QKeySequence("Ctrl+o"),
            )
        )

    @Slot(QModelIndex)
    def on_file_selected(self, index: QModelIndex):
        path = Path(self.file_model.filePath(index))
        if path.exists() and not path.is_dir():
            self.sig_file_selected.emit(path)

    def set_root_from_dialog(self):
        dir: str = QFileDialog.getExistingDirectory(
            caption="Open Routines Directory", dir=self.root_path
        )
        self.root_path = dir
        self.file_model.setRootPath(dir)
        root_index: QModelIndex = self.file_model.index(dir)
        if root_index.isValid():
            self.setRootIndex(root_index)
