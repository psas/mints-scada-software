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


def test_file_explorer_set_root_from_path_sets_root_path(
    file_explorer: FileExplorerWidget, tmp_path: Path
):
    """
    When set_root_from_path is called with a directory, the widget's root_path should
    be updated to that directory
    """
    file_explorer.set_root_from_path(tmp_path)
    assert file_explorer.root_path == tmp_path


def test_file_explorer_set_root_from_file_uses_parent_dir_for_file(
    file_explorer: FileExplorerWidget, tmp_path: Path
):
    """
    When set_root_from_file is called with a path to a file, the widget's root should
    be set to that file's parent directory
    """
    test_file = tmp_path / "test.txt"
    test_file.write_text("contents")

    file_explorer.set_root_from_file(test_file)

    assert file_explorer.root_path == tmp_path


def test_file_explorer_set_root_from_file_uses_dir_directly_for_directory(
    file_explorer: FileExplorerWidget, tmp_path: Path
):
    """
    When set_root_from_file is called with a path to a directory, the widget's root
    should be set to that directory itself
    """
    file_explorer.set_root_from_file(tmp_path)
    assert file_explorer.root_path == tmp_path


def test_file_explorer_on_file_selected_emits_signal_for_file(
    file_explorer: FileExplorerWidget, tmp_path: Path, qtbot: QtBot
):
    """
    When on_file_selected is triggered with an index pointing to an existing file, it
    should emit sig_file_selected with that file's path
    """
    test_file = tmp_path / "test.txt"
    test_file.write_text("contents")
    file_explorer.set_root_from_path(tmp_path)
    file_explorer.file_model.setRootPath(str(tmp_path))

    index = file_explorer.file_model.index(str(test_file))

    with qtbot.waitSignal(file_explorer.sig_file_selected, timeout=1000) as blocker:
        file_explorer.on_file_selected(index)

    assert blocker.args == [test_file]


def test_file_explorer_on_file_selected_does_not_emit_for_directory(
    file_explorer: FileExplorerWidget, tmp_path: Path, qtbot: QtBot
):
    """
    When on_file_selected is triggered with an index pointing to a directory, it
    should not emit sig_file_selected
    """
    file_explorer.set_root_from_path(tmp_path)
    file_explorer.file_model.setRootPath(str(tmp_path))

    index = file_explorer.file_model.index(str(tmp_path))

    with qtbot.assertNotEmitted(file_explorer.sig_file_selected):
        file_explorer.on_file_selected(index)
