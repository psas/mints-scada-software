from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, Signal, Slot
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
        self.root_path: Path = Path(QDir.currentPath())

        self.file_model.setIconProvider(self.icon_provider)
        self.file_model.setReadOnly(True)

        self.setModel(self.file_model)
        self.set_root_from_path(self.root_path)
        self.setAnimated(True)
        self.setSortingEnabled(False)
        self.setHeaderHidden(True)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)

        for col in range(1, self.file_model.columnCount()):
            self.hideColumn(col)

        self.doubleClicked.connect(self.on_file_selected)

        add_to_menu(
            MenuEntry(
                menu="File",
                desc="Open folder",
                callback=self.set_root_from_dialog,
                shortcut="Ctrl+shift+o",
            )
        )

    @Slot(QModelIndex)
    def on_file_selected(self, index: QModelIndex):
        path = Path(self.file_model.filePath(index))
        if path.exists() and not path.is_dir():
            self.sig_file_selected.emit(path)

    @Slot(Path)
    def set_root_from_file(self, path: Path):
        if path.is_dir():
            directory = path
        else:
            directory = path.parent
        self.set_root_from_path(directory)

    def set_root_from_dialog(self):
        directory: str = QFileDialog.getExistingDirectory(
            caption="Open Folder", dir=str(self.root_path)
        )
        self.set_root_from_path(Path(directory))

    def set_root_from_path(self, path: Path):
        self.root_path = path
        self.file_model.setRootPath(str(path))
        root_index: QModelIndex = self.file_model.index(str(path))
        if root_index.isValid():
            self.setRootIndex(root_index)
