from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QMenu,
    QMenuBar,
)

MenuTypes = Literal["File", "View"]


class MenuBar(QMenuBar):
    def __init__(
        self,
        menu_entries: list[MenuEntry],
    ):
        super().__init__()
        self.file_menu = QMenu("File")
        self.view_menu = QMenu("View")

        for entry in menu_entries:
            match entry.menu:
                case "File":
                    self.file_menu.addAction(
                        entry.desc,
                        entry.callback,
                        entry.shortcut if entry.shortcut is not None else 0,
                    )
                case "View":
                    self.view_menu.addAction(
                        entry.desc,
                        entry.callback,
                        entry.shortcut if entry.shortcut is not None else 0,
                    )

        self.addMenu(self.file_menu)
        self.addMenu(self.view_menu)


@dataclass(frozen=True)
class MenuEntry:
    menu: MenuTypes
    desc: str
    callback: Callable
    shortcut: QKeySequence | None
