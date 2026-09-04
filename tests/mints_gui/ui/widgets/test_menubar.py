import pytest
from pytestqt.qtbot import QtBot

from mints_gui.ui.widgets.menubar import MenuBar, MenuEntry


@pytest.fixture()
def menubar(qtbot: QtBot):
    menubar = MenuBar()
    yield menubar


@pytest.fixture()
def menuentry():
    menuentry = MenuEntry("File", "Test entry", lambda: "Test Success", None)
    yield menuentry


@pytest.fixture()
def menu_with_entry(menubar: MenuBar, menuentry: MenuEntry):
    menu_with_entry = menubar
    menu_with_entry.add_to_menu(menuentry)
    yield menu_with_entry
    menu_with_entry.clear()


def test_add_to_menu_bar(menubar: MenuBar, menuentry: MenuEntry):
    """
    Adding an action to the menu bar using the add_to_menu method should work properly
    """
    assert menubar.file_menu.isEmpty()
    menubar.add_to_menu(menuentry)
    assert not menubar.file_menu.isEmpty()
    action = next(iter(menubar.file_menu.actions()))
    assert action.text() == menuentry.desc


def test_menu_action_after_add(qtbot: QtBot, menu_with_entry: MenuBar):
    """
    The added action should trigger successfully when triggered
    """
    qtbot.addWidget(menu_with_entry)
    action = next(iter(menu_with_entry.file_menu.actions()))
    with qtbot.waitSignal(action.triggered, timeout=1000):
        action.trigger()
