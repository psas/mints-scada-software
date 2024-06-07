from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit
from gui import QLoggingHandler
import logging

class ConsoleView(QWidget):
    def __init__(self, loghandler: QLoggingHandler):
        super().__init__()
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.loghandler = loghandler or QLoggingHandler()
        self.layout.addWidget(self.loghandler.widget)