from PyQt5 import QtWidgets
# from PyQt5.QtWidgets import QApplication, QMainWindow, QDialog, QHBoxLayout, QPushButton, QLabel
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QPalette, QColor, QFont
from PyQt5.QtCore import Qt

from nexus.genericsensor import GenericSensor
from gui import ListTab, GraphTab, ExportTab, ConsoleTab

class MainWindow(QDialog):
    def __init__(self, parent=None, loghandler=None):
        super(MainWindow, self).__init__(parent)

        self.setWindowTitle("CAN bus sensor demo")
        self.setGeometry(0, 0, 960, 540)

        # Force the style to be the same on all OSs:
        QApplication.setStyle("Fusion")

        # Now use a palette to switch to dark colors:
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ToolTipBase, Qt.white)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        QApplication.setPalette(palette)

        font = QFont("Monospace")
        # font.setStyleHint(QFont.Monospace)
        self.setFont(font)

        self.mainlayout = QVBoxLayout(self)

        self.tabs = QTabWidget()

        self.graph = GraphTab()
        self.tabs.addTab(self.graph, "Graph")

        self.listtab = ListTab()
        self.tabs.addTab(self.listtab, "List")

        # self.exporter = ExportTab()
        # self.tabs.addTab(self.exporter, "Export")

        self.console = ConsoleTab(loghandler)
        self.tabs.addTab(self.console, "Console")

        self.mainlayout.addWidget(self.tabs)
        self.setLayout(self.mainlayout)

    def update(self):
        pass