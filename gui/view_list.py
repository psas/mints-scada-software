"""gui/view_list.py

List-view widget container used by the GUI view layer.
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtCore import Qt


class ListView(QWidget):
    """Provide a top-aligned vertical container for list-style child widgets."""

    def __init__(self):
        """Initialize the widget with a top-aligned vertical layout."""
        super().__init__()
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.layout.setAlignment(Qt.AlignTop)
