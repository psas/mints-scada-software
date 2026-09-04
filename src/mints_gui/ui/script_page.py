from collections.abc import Callable

from pyqtgraph.dockarea.Dock import Dock
from pyqtgraph.dockarea.DockArea import DockArea

from mints_gui.logging import LogConsoleWidget, SignalHandler
from mints_gui.ui.widgets.file_explorer import FileExplorerWidget
from mints_gui.ui.widgets.script_editor import ScriptEditor


class ScriptPage(DockArea):
    def __init__(self, log_signal: SignalHandler, add_to_menu: Callable):
        super().__init__()
        script_editor = ScriptEditor()
        file_explorer = FileExplorerWidget(add_to_menu)
        log_widget = LogConsoleWidget()

        file_dock = Dock("File Explorer", size=(1, 1000))
        file_dock.hideTitleBar()
        file_dock.addWidget(file_explorer)
        self.addDock(file_dock, "left")

        log_dock = Dock("Log")
        log_dock.hideTitleBar()
        log_dock.addWidget(log_widget)
        self.addDock(log_dock, "bottom", relativeTo=file_dock)

        script_dock = Dock("Script Editor", size=(1000, 1000))
        script_dock.hideTitleBar()
        script_dock.addWidget(script_editor)
        self.addDock(script_dock, "right")

        log_signal.sig_output_log.connect(log_widget.appendPlainText)
        file_explorer.sig_file_selected.connect(script_editor.set_active_file)
