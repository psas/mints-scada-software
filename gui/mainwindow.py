from PyQt5.QtWidgets import *
from PyQt5.QtGui import QPalette, QColor, QFont
from PyQt5.QtCore import Qt

from gui import ListView, GraphView, ExportView, ConsoleView, ScriptView, MintsScriptAPI, AutoPollerRow

from nexus import BusRider

import logging

class MainWindow(QDialog):
    def __init__(self, parent=None, loghandler=None, autopoller=None):
        super(MainWindow, self).__init__(parent)

        self.autopoller = autopoller

        self.log = logging.getLogger("mainwindow")

        self.devices: map[BusRider] = {}

        self.setWindowTitle("minTS Controller")
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

        self.graph = GraphView()
        self.listtab = ListView()
        self.console = ConsoleView(loghandler)
        self.exporter = ExportView()
        self.scripter = ScriptView(MintsScriptAPI(devices=self.devices, graph=self.graph, exporter=self.exporter, autopoller=self.autopoller, abort=self.abort))

        self.tabs = QTabWidget()
        self.tabs.addTab(self.graph, "Graph")
        self.tabs.addTab(self.listtab, "List")
        # self.tabs.addTab(self.exporter, "Export")
        self.tabs.addTab(self.scripter, "Script")
        self.tabs.addTab(self.console, "Console")
        self.mainlayout.addWidget(self.tabs)

        self.tabs.setCurrentIndex(2)

        # If you don't like tabs, everything can be side by side
        # self.container = QHBoxLayout()
        # self.container.addWidget(self.graph)
        # self.container.addWidget(self.listtab)
        # self.container.addWidget(self.console)
        # self.mainlayout.addLayout(self.container)

        apr = AutoPollerRow(self.autopoller)
        self.mainlayout.addLayout(apr)

        self.setLayout(self.mainlayout)

    def addDevice(self, device: BusRider, display: QWidget = None):
        self.devices[device.name] = device
        if display is not None:
            self.listtab.layout.addLayout(display)
        self.graph.addSensor(device, display is not None)

    def update(self):
        pass

    def abort(self):
        self.log.fatal("Nooooo I don't know how to abort! This is bad! Slap the big red button NOWWWWW!!!!")