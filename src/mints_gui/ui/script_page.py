from PySide6.QtWidgets import QWidget


class ScriptPage(QWidget):
    def __init__(self):
        super().__init__()
        add_to_menu(
            menu="File",
            desc="Open Folder",
            callback=self.file_explorer.set_root_from_dialog,
            shortcut=QKeySequence("Ctrl+o"),
        )
