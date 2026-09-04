from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from mints_gui.ui.widgets.file_explorer import FileExplorerWidget


@pytest.fixture()
def file_explorer(qtbot: QtBot, tmp_path: Path):
    file_explorer = FileExplorerWidget(add_to_menu=lambda arg: None)
    qtbot.addWidget(file_explorer)
    file_explorer.file_model.setRootPath(str(tmp_path))
    root_index = file_explorer.file_model.index(str(tmp_path))
    file_explorer.setRootIndex(root_index)
    yield file_explorer


def test_sig_file_selected_emits_path_for_file(
    qtbot: QtBot, file_explorer: FileExplorerWidget, tmp_path: Path
):
    """
    The file explorer should emit a signal with the path of a file
    when it's on_file_selected method is called
    """
    test_file = tmp_path / "test.txt"
    test_file.write_text("testing")
    file_index = file_explorer.file_model.index(str(test_file))

    with qtbot.waitSignal(file_explorer.sig_file_selected, timeout=1000) as blocker:
        file_explorer.on_file_selected(file_index)

    assert blocker.args == [test_file]
