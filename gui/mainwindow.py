print("hi")
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont

import qdarkstyle

from gui import ListView, GraphView, ExportView, ConsoleView, ScriptView, MintsScriptAPI, AutoPollerRow

from nexus import BusRider

import logging

class MainWindow(QDialog):
    def __init__(self, parent=None, loghandler=None, autopoller=None):
        super(MainWindow, self).__init__(parent)

        logging.getLogger("qdarkstyle").setLevel(logging.ERROR)

        self.autopoller = autopoller

        self.log = logging.getLogger("mainwindow")

        self.devices: map[BusRider] = {}

        self.setWindowTitle("minTS Controller")
        self.setGeometry(0, 0, 960, 540)

        # Force the style to be the same on all OSs:
        QApplication.setStyle("Fusion")

        # Set dark theme
        self.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt5'))
        
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

        self.tabs.setCurrentIndex(1)

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
        self.exporter.devices.append(device)
        if display is not None:
            self.listtab.layout.addLayout(display)
        self.graph.addSensor(device, display is not None)

    def update(self):
        pass

    def abort(self):
        self.log.fatal("Nooooo I don't know how to abort! This is bad! Slap the big red button NOWWWWW!!!!")