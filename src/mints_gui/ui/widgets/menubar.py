from PySide6.QtWidgets import (
    QMenu,
    QMenuBar,
)


class MenuBar(QMenuBar):
    def __init__(
        self,
        restore_default_area_state,
    ):
        super().__init__()
        self.view_menu = QMenu("View")
        self.view_menu.addAction(
            "Revert devices to default layout", restore_default_area_state
        )
        self.addMenu(self.view_menu)
