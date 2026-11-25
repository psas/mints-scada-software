from pathlib import Path
from unittest.mock import Mock

import pytest
from pytestqt.qtbot import QtBot

from mints_gui.ui.widgets.script_toolbar import InfoBox, ScriptToolbar


@pytest.fixture()
def infobox(qtbot: QtBot):
    infobox = InfoBox()
    qtbot.addWidget(infobox)
    yield infobox


@pytest.fixture()
def script_toolbar(qtbot: QtBot):
    def add_to_menu(*args):
        pass

    run_script = Mock()
    runner_stop = Mock()
    script_toolbar = ScriptToolbar(run_script, runner_stop, add_to_menu)
    qtbot.addWidget(script_toolbar)
    yield script_toolbar


def test_script_toolbar_set_active_file_sets_filename_label(
    script_toolbar: ScriptToolbar, tmp_path: Path
):
    """
    When set_active_file is called with a path, the toolbar should set its active_file
    and update the info box's filename label to the file's name
    """
    test_file = tmp_path / "test.py"
    script_toolbar.set_active_file(test_file)

    assert script_toolbar.active_file == test_file
    assert script_toolbar.info_box.filename.text() == "test.py"


def test_script_toolbar_on_new_file_clears_active_file_and_label(
    script_toolbar: ScriptToolbar, tmp_path: Path
):
    """
    When on_new_file is called, the toolbar should clear the active file and the
    filename label, and clear the file-modified label
    """
    test_file = tmp_path / "test.py"
    script_toolbar.set_active_file(test_file)
    script_toolbar.info_box.set_file_modified(True)

    script_toolbar.on_new_file()

    assert script_toolbar.active_file == Path()
    assert script_toolbar.info_box.filename.text() == ""
    assert script_toolbar.info_box.changes_saved.text() == ""


def test_script_toolbar_play_calls_run_script(script_toolbar: ScriptToolbar):
    """
    When play is called, it should call the run_script callable passed at construction
    """
    script_toolbar.play()
    script_toolbar.run_script.assert_called_once()  # pyright: ignore[reportFunctionMemberAccess]


def test_script_toolbar_stop_calls_stop_running_script(script_toolbar: ScriptToolbar):
    """
    When stop is called, it should call the runner_stop callable passed at construction
    """
    script_toolbar.stop()
    script_toolbar.stop_running_script.assert_called_once()  # pyright: ignore[reportFunctionMemberAccess]


def test_script_toolbar_show_running_label_sets_text(script_toolbar: ScriptToolbar):
    """
    When show_running_label is called, the running label should display "Running"
    """
    script_toolbar.show_running_label()
    assert script_toolbar.controls.running_label.text() == "Running"


def test_script_toolbar_hide_running_label_clears_text(script_toolbar: ScriptToolbar):
    """
    When hide_running_label is called, the running label should be cleared
    """
    script_toolbar.show_running_label()
    script_toolbar.hide_running_label()
    assert script_toolbar.controls.running_label.text() == ""


def test_info_box_set_file_modified_true_sets_message(qtbot: QtBot, infobox: InfoBox):
    """
    When set_file_modified is called with True, the changes_saved label should show
    the modified message
    """
    infobox.set_file_modified(True)
    assert infobox.changes_saved.text() == "File modified since last save"


def test_info_box_set_file_modified_false_clears_message(
    qtbot: QtBot, infobox: InfoBox
):
    """
    When set_file_modified is called with False, the changes_saved label should be
    empty
    """
    infobox.set_file_modified(True)
    infobox.set_file_modified(False)

    assert infobox.changes_saved.text() == ""
