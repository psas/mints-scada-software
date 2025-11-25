print("hi")
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

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

        self.setWindowTitle("minTS Controller - Dashboard")
        self.setGeometry(0, 0, 1400, 800)  # Larger window for dashboard layout

        # Force the style to be the same on all OSs:
        QApplication.setStyle("Fusion")

        # Set dark theme
        self.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt5'))

        # Use readable font for UI, monospace only for data
        font = QFont("Arial", 9)
        self.setFont(font)

        self.mainlayout = QVBoxLayout(self)
        self.mainlayout.setSpacing(5)
        self.mainlayout.setContentsMargins(5, 5, 5, 5)

        # Title bar with status
        self._create_title_bar()

        # Create views
        self.graph = GraphView()
        self.listtab = ListView()
        self.console = ConsoleView(loghandler)
        self.exporter = ExportView()
        self.scripter = ScriptView(MintsScriptAPI(
            devices=self.devices,
            graph=self.graph,
            exporter=self.exporter,
            autopoller=self.autopoller,
            abort=self.abort
        ))

        # Create unified dashboard layout
        self._create_dashboard_layout()

        # AutoPoller control at bottom
        apr = AutoPollerRow(self.autopoller)
        self.mainlayout.addLayout(apr)

        self.setLayout(self.mainlayout)

    def _create_title_bar(self):
        """Create title bar with status information"""
        title_widget = QWidget()
        title_widget.setStyleSheet("""
            QWidget {
                background-color: #232629;
                border-bottom: 2px solid #4CAF50;
                padding: 5px;
            }
        """)
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(10, 5, 10, 5)

        # Title
        title_label = QLabel("minTS Controller")
        title_label.setFont(QFont("Arial", 14, QFont.Bold))
        title_layout.addWidget(title_label)

        title_layout.addStretch()

        # Status indicator
        self.status_indicator = QLabel("● Connected")
        self.status_indicator.setStyleSheet("color: #4CAF50; font-weight: bold;")
        self.status_indicator.setFont(QFont("Arial", 10))
        title_layout.addWidget(self.status_indicator)

        self.mainlayout.addWidget(title_widget)

    def _create_dashboard_layout(self):
        """
        Create unified dashboard layout with all sections visible
        """

        # Main horizontal splitter (Left | Right)
        main_splitter = QSplitter(Qt.Horizontal)

        # Left column (Devices + Script)
        left_splitter = QSplitter(Qt.Vertical)

        # Device List section
        device_panel = self._create_panel("Devices", self.listtab)
        left_splitter.addWidget(device_panel)

        # Script Control section
        script_panel = self._create_panel("Script Control", self.scripter)
        left_splitter.addWidget(script_panel)

        left_splitter.setSizes([400, 300])  # Initial sizes

        # Right column (Graph + Console)
        right_splitter = QSplitter(Qt.Vertical)

        # Graph section
        graph_panel = self._create_panel("Real-Time Graph", self.graph)
        right_splitter.addWidget(graph_panel)

        # Console section
        console_panel = self._create_panel("Console Log", self.console)
        right_splitter.addWidget(console_panel)

        right_splitter.setSizes([450, 250])  # Initial sizes

        # Add to main splitter
        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(right_splitter)

        # Set initial sizes (40% left, 60% right)
        main_splitter.setSizes([560, 840])

        self.mainlayout.addWidget(main_splitter)

    def _create_panel(self, title, widget):
        """Create a panel with title bar and content"""
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setSpacing(0)
        panel_layout.setContentsMargins(0, 0, 0, 0)

        # Panel title bar
        title_bar = QLabel(title)
        title_bar.setFont(QFont("Arial", 11, QFont.Bold))
        title_bar.setStyleSheet("""
            QLabel {
                background-color: #2a2d2f;
                color: #ffffff;
                padding: 8px;
                border-bottom: 1px solid #4CAF50;
            }
        """)
        panel_layout.addWidget(title_bar)

        # Panel content
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(5, 5, 5, 5)
        content_layout.addWidget(widget)

        panel_layout.addWidget(content_widget)

        return panel

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