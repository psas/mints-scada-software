from PySide6.QtCore import QDir, QModelIndex
from PySide6.QtWidgets import (
    QFileDialog,
    QFileIconProvider,
    QFileSystemModel,
    QTreeView,
)


class FileExplorerWidget(QTreeView):
    def __init__(self):
        super().__init__()
        self.file_model = QFileSystemModel()
        self.icon_provider = QFileIconProvider()
        self.file_model.setIconProvider(self.icon_provider)
        self.root_path: str = QDir.currentPath()
        self.file_model.setRootPath(self.root_path)
        self.setModel(self.file_model)
        root_index: QModelIndex = self.file_model.index(self.root_path)
        if root_index.isValid():
            self.setRootIndex(root_index)
        self.setAnimated(True)
        self.setSortingEnabled(False)
        self.set_root_from_dialog()

    def set_root_from_dialog(self):
        dir: str = QFileDialog.getExistingDirectory(
            caption="Open Routines Directory", dir=self.root_path
        )
        self.root_path = dir
        self.file_model.setRootPath(dir)
        root_index: QModelIndex = self.file_model.index(dir)
        if root_index.isValid():
            self.setRootIndex(root_index)
