from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QMenu,
    QMenuBar,
)

logger = logging.getLogger(__name__)

MenuTypes = Literal["File", "Edit", "View"]


class MenuBar(QMenuBar):
    def __init__(self):
        super().__init__()
        self.file_menu = QMenu("File")
        self.edit_menu = QMenu("Edit")
        self.view_menu = QMenu("View")
        self.addMenu(self.file_menu)
        self.addMenu(self.edit_menu)
        self.addMenu(self.view_menu)

    def add_to_menu(self, entry: MenuEntry):
        shortcut = (
            QKeySequence(entry.shortcut)
            if entry.shortcut is not None
            else QKeySequence()
        )

        match entry.menu:
            case "File":
                self.file_menu.addAction(
                    entry.desc,
                    entry.callback,
                    shortcut,
                )
            case "Edit":
                self.edit_menu.addAction(
                    entry.desc,
                    entry.callback,
                    shortcut,
                )
            case "View":
                self.view_menu.addAction(
                    entry.desc,
                    entry.callback,
                    shortcut,
                )
            case _:
                logger.error("Unhandled menu type '%s'", entry.menu)


@dataclass(frozen=True)
class MenuEntry:
    menu: MenuTypes
    desc: str
    callback: Callable
    shortcut: str | None = None
