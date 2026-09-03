from collections.abc import Callable

from pyqtgraph import LayoutWidget

from mints_gui.ui.widgets.file_explorer import FileExplorerWidget
from mints_gui.ui.widgets.logger import LogConsoleWidget, SignalHandler
from mints_gui.ui.widgets.script_editor import ScriptEditor


class ScriptPage(LayoutWidget):
    def __init__(self, log_signal: SignalHandler, add_to_menu: Callable):
        super().__init__()
        self.script_editor = ScriptEditor()
        self.file_explorer = FileExplorerWidget(add_to_menu)
        self.log_widget = LogConsoleWidget()

        self.addWidget(self.file_explorer, 0, 0, rowspan=2, colspan=2)
        self.addWidget(self.log_widget, 2, 0, colspan=2)
        self.addWidget(self.script_editor, 0, 2, rowspan=3, colspan=6)

        log_signal.sig_output_log.connect(self.log_widget.appendPlainText)
        self.file_explorer.sig_file_selected.connect(self.script_editor.set_active_file)
