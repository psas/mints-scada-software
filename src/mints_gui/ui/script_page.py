from collections.abc import Callable

from pyqtgraph import LayoutWidget

from mints_gui.ui.widgets.file_explorer import FileExplorerWidget
from mints_gui.ui.widgets.script_editor import ScriptEditor


class ScriptPage(LayoutWidget):
    def __init__(self, add_to_menu: Callable):
        super().__init__()
        self.script_editor = ScriptEditor()
        self.file_explorer = FileExplorerWidget(add_to_menu)
        self.addWidget(self.file_explorer, 0, 0)
        self.addWidget(self.script_editor, 0, 1)

        self.file_explorer.sig_file_selected.connect(self.script_editor.set_active_file)
