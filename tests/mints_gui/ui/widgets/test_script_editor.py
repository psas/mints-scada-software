from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from mints_gui.ui.widgets.script_editor import ScriptEditor


@pytest.fixture()
def script_editor(qtbot: QtBot):
    script_editor = ScriptEditor()
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
