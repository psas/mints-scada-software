from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from mints_backend.script_runner import ScriptRunner
from mints_gui.ui.widgets.script_editor import NEW_FILE_TEXT, ScriptEditor


@pytest.fixture()
def script_editor(qtbot: QtBot, script_runner: ScriptRunner):
    def add_to_menu(*args):
        pass

    script_editor = ScriptEditor(script_runner.run, add_to_menu)
    qtbot.addWidget(script_editor)
    yield script_editor


def test_script_editor_sets_text_to_active_file(
    script_editor: ScriptEditor, tmp_path: Path
):
    """
    When the set_active_file method is called with a path, the script editor should set
    its inner text to the contents of that file
    """
    test_file = tmp_path / "test.txt"
    txt = "testing 123"
    test_file.write_text(txt)

    script_editor.set_active_file(test_file)

    assert script_editor.toPlainText() == txt


def test_script_editor_new_file_resets_text_and_active_file(
    script_editor: ScriptEditor, tmp_path: Path
):
    """
    When new_file is called with no unsaved changes, the editor should reset its text to
    NEW_FILE_TEXT and clear the active file
    """
    test_file = tmp_path / "test.txt"
    test_file.write_text("some contents")
    script_editor.set_active_file(test_file)

    script_editor.new_file()

    assert script_editor.toPlainText() == NEW_FILE_TEXT
    assert script_editor.active_file == Path()


def test_script_editor_save_file_writes_to_active_file(
    script_editor: ScriptEditor, tmp_path: Path
):
    """
    When save_file is called on an editor with an active file, it should write the
    current text to that file
    """
    test_file = tmp_path / "test.txt"
    test_file.write_text("old contents")
    script_editor.set_active_file(test_file)

    txt = "new contents"
    script_editor.setPlainText(txt)
    script_editor.save_file()

    assert test_file.read_text() == txt


def test_script_editor_save_file_emits_sig_file_saved(
    script_editor: ScriptEditor, tmp_path: Path, qtbot: QtBot
):
    """
    When save_file is called on an editor with an active file, it should emit
    sig_file_saved with the active file path
    """
    test_file = tmp_path / "test.txt"
    test_file.write_text("contents")
    script_editor.set_active_file(test_file)

    with qtbot.waitSignal(script_editor.sig_file_saved, timeout=1000) as blocker:
        script_editor.save_file()

    assert blocker.args == [test_file]


def test_script_editor_check_for_file_modified_true_when_text_differs(
    script_editor: ScriptEditor, tmp_path: Path
):
    """
    When the editor's text differs from the active file's contents, file_modified
    should be set to True
    """
    test_file = tmp_path / "test.txt"
    test_file.write_text("original")
    script_editor.set_active_file(test_file)

    script_editor.setPlainText("changed")

    assert script_editor.file_modified is True


def test_script_editor_check_for_file_modified_false_when_text_matches(
    script_editor: ScriptEditor, tmp_path: Path
):
    """
    When the editor's text matches the active file's contents, file_modified should
    be set to False
    """
    test_file = tmp_path / "test.txt"
    txt = "matching contents"
    test_file.write_text(txt)
    script_editor.set_active_file(test_file)

    script_editor.setPlainText(txt)

    assert script_editor.file_modified is False


def test_script_editor_new_file_emits_sig_file_new(
    script_editor: ScriptEditor, qtbot: QtBot
):
    """
    When new_file is called with no unsaved changes, it should emit sig_file_new
    """
    with qtbot.waitSignal(script_editor.sig_file_new, timeout=1000):
        script_editor.new_file()
