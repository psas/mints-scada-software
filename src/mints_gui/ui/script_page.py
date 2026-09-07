from collections.abc import Callable
from pathlib import Path

from pyqtgraph.dockarea.Dock import Dock
from pyqtgraph.dockarea.DockArea import DockArea
from PySide6.QtWidgets import QVBoxLayout, QWidget

from mints_backend.script_runner import ScriptRunner
from mints_gui.logging import LogConsoleWidget, SignalHandler
from mints_gui.ui.widgets.file_explorer import FileExplorerWidget
from mints_gui.ui.widgets.script_editor import ScriptEditor
from mints_gui.ui.widgets.script_toolbar import ScriptToolbar


class ScriptPage(DockArea):
    def __init__(
        self, log_signal: SignalHandler, runner: ScriptRunner, add_to_menu: Callable
    ):
        super().__init__()
        script_widget = ScriptWidget(runner, add_to_menu)
        log_widget = LogConsoleWidget()
        file_explorer = FileExplorerWidget(add_to_menu)

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
        script_dock.addWidget(script_widget)
        self.addDock(script_dock, "right")

        log_signal.sig_output_log.connect(log_widget.appendPlainText)

        file_explorer.sig_file_selected.connect(script_widget.on_file_select)
        script_widget.script_editor.sig_file_opened.connect(
            file_explorer.set_root_from_file
        )


class ScriptWidget(QWidget):
    def __init__(self, runner: ScriptRunner, add_to_menu: Callable):
        super().__init__()
        self.script_editor = ScriptEditor(runner.run, add_to_menu)
        self.script_toolbar = ScriptToolbar(
            self.script_editor.run_script, runner.stop, add_to_menu
        )
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.script_toolbar, 0)
        layout.addWidget(self.script_editor, 1)
        self.setLayout(layout)

        self.script_editor.sig_file_opened.connect(self.on_file_select)
        self.script_editor.sig_file_saved.connect(self.on_file_select)
        self.script_editor.sig_file_new.connect(self.script_toolbar.unset_active_file)
        self.script_editor.sig_file_changed.connect(
            self.script_toolbar.info_box.on_file_changed
        )
        self.script_editor.sig_file_saved.connect(
            self.script_toolbar.info_box.on_file_saved
        )
        runner.process.finished.connect(self.script_toolbar.hide_running_label)

    def on_file_select(self, path: Path) -> None:
        self.script_editor.set_active_file(path)
        self.script_toolbar.set_active_file(path)
        self.script_toolbar.info_box.on_file_load()
