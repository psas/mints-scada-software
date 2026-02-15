# 
# 
# 
# 
# 
# 
# 
# 
# 
# This mainwindow.py no longer in use. Windows now move to window_manager.py
# 
# 
# 
# 
# 
# 
# 
# 
# 
# 
# 
print("hi")
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QTimer, QTime

import qdarkstyle

from gui import ListView, GraphView, ExportView, ConsoleView, ScriptView, MintsScriptAPI, AutoPollerRow
from gui.timelineview import TimelineView

from nexus import BusRider

import logging
from datetime import datetime, timedelta

class MainWindow(QDialog):
    def __init__(self, parent=None, loghandler=None, autopoller=None, playback_mode=False, test_name=None):
        super(MainWindow, self).__init__(parent)

        logging.getLogger("qdarkstyle").setLevel(logging.ERROR)

        self.autopoller = autopoller
        self.playback_mode = playback_mode
        self.test_name = test_name  # Name of test being played back
        self.change_test_requested = False  # Track if user wants to change test

        self.log = logging.getLogger("mainwindow")

        self.devices: map[BusRider] = {}

        # Mission timer tracking
        self.mission_start_time = None
        self.mission_running = False

        # Playback mode specific
        self.playback_time = 0.0  # Current playback time in seconds (for playback mode)

        # Set window title based on mode
        if self.playback_mode and self.test_name:
            self.setWindowTitle(f"minTS Controller - Playback: {self.test_name}")
        else:
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

        # Timeline bar (shown in both live and playback modes) - moved to top
        self.timeline = TimelineView(playback_mode=self.playback_mode)
        self.mainlayout.addWidget(self.timeline)

        # Connect timeline seek signal for playback mode
        if self.playback_mode:
            self.timeline.seek_requested.connect(self._on_timeline_seek)

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

        # AutoPoller control at bottom (only in live mode)
        if self.autopoller is not None:
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

        # Mission elapsed time (T+ or T-)
        self.mission_time_label = QLabel("T+00:00:00.000000")
        self.mission_time_label.setFont(QFont("Courier New", 18, QFont.Bold))
        self.mission_time_label.setStyleSheet("""
            color: #00FF00;
            padding: 0 20px;
            text-decoration: none;
            border: none;
        """)
        self.mission_time_label.setAlignment(Qt.AlignCenter)
        title_layout.addWidget(self.mission_time_label)

        title_layout.addStretch()

        # Current wall clock time
        self.clock_label = QLabel("00:00:00")
        self.clock_label.setFont(QFont("Courier New", 11))
        self.clock_label.setStyleSheet("color: #aaaaaa; padding: 0 15px;")
        title_layout.addWidget(self.clock_label)

        # Status indicator
        if self.playback_mode:
            # if self.test_name:
            #     self.status_indicator = QLabel(f"● Playback: {self.test_name}")
            # else:
            self.status_indicator = QLabel("● Playback")
            self.status_indicator.setStyleSheet("color: #FFA726; font-weight: bold;")  # Yellow/Orange
        else:
            self.status_indicator = QLabel("● Connected")
            self.status_indicator.setStyleSheet("color: #4CAF50; font-weight: bold;")  # Green
        self.status_indicator.setFont(QFont("Arial", 10))
        title_layout.addWidget(self.status_indicator)

        self.mainlayout.addWidget(title_widget)

        # Start timer to update displays
        self.display_timer = QTimer(self)
        self.display_timer.timeout.connect(self._update_time_displays)
        self.display_timer.start(100)  # Update every 100ms for smooth display

    def _create_dashboard_layout(self):
        """
        Create unified dashboard layout with all sections visible
        """

        # Main horizontal splitter (Left | Middle | Right Control Panel)
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

        # Middle column (Graph + Console)
        middle_splitter = QSplitter(Qt.Vertical)

        # Graph section
        graph_panel = self._create_panel("Real-Time Graph", self.graph)
        middle_splitter.addWidget(graph_panel)

        # Console section
        console_panel = self._create_panel("Console Log", self.console)
        middle_splitter.addWidget(console_panel)

        middle_splitter.setSizes([450, 250])  # Initial sizes

        # Right column (Control Panel)
        control_panel = self._create_control_panel()

        # Add to main splitter
        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(middle_splitter)
        main_splitter.addWidget(control_panel)

        # Set initial sizes (35% left, 50% middle, 15% right control)
        main_splitter.setSizes([490, 700, 210])

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

    def _create_control_panel(self):
        """Create vertical control panel with process control buttons"""
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setSpacing(0)
        panel_layout.setContentsMargins(0, 0, 0, 0)

        # Panel title bar
        title_bar = QLabel("Process Control")
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

        # Control buttons container
        controls_widget = QWidget()
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setSpacing(15)
        controls_layout.setContentsMargins(10, 20, 10, 10)

        # START button (Green)
        self.start_button = QPushButton("START")
        self.start_button.setFont(QFont("Arial", 14, QFont.Bold))
        self.start_button.setMinimumHeight(80)
        self.start_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: 3px solid #45a049;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #45a049;
                border: 3px solid #3d8b40;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        self.start_button.clicked.connect(self._on_start_clicked)
        controls_layout.addWidget(self.start_button)

        # SOFT STOP button (Orange/Amber)
        self.soft_stop_button = QPushButton("SOFT STOP")
        self.soft_stop_button.setFont(QFont("Arial", 14, QFont.Bold))
        self.soft_stop_button.setMinimumHeight(80)
        self.soft_stop_button.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: 3px solid #F57C00;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #F57C00;
                border: 3px solid #E65100;
            }
            QPushButton:pressed {
                background-color: #E65100;
            }
        """)
        self.soft_stop_button.clicked.connect(self._on_soft_stop_clicked)
        controls_layout.addWidget(self.soft_stop_button)

        # HARD STOP button (Red)
        self.hard_stop_button = QPushButton("HARD STOP")
        self.hard_stop_button.setFont(QFont("Arial", 14, QFont.Bold))
        self.hard_stop_button.setMinimumHeight(80)
        self.hard_stop_button.setStyleSheet("""
            QPushButton {
                background-color: #F44336;
                color: white;
                border: 3px solid #d32f2f;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
                border: 3px solid #b71c1c;
            }
            QPushButton:pressed {
                background-color: #b71c1c;
            }
        """)
        self.hard_stop_button.clicked.connect(self._on_hard_stop_clicked)
        controls_layout.addWidget(self.hard_stop_button)

        # Add stretch to push buttons to top
        controls_layout.addStretch()

        # CHANGE TEST button (only in playback mode) - Blue
        if self.playback_mode:
            self.change_test_button = QPushButton("CHANGE TEST")
            self.change_test_button.setFont(QFont("Arial", 12, QFont.Bold))
            self.change_test_button.setMinimumHeight(60)
            self.change_test_button.setStyleSheet("""
                QPushButton {
                    background-color: #2196F3;
                    color: white;
                    border: 3px solid #1976D2;
                    border-radius: 8px;
                    padding: 10px;
                }
                QPushButton:hover {
                    background-color: #1976D2;
                    border: 3px solid #0D47A1;
                }
                QPushButton:pressed {
                    background-color: #0D47A1;
                }
            """)
            self.change_test_button.clicked.connect(self._on_change_test_clicked)
            controls_layout.addWidget(self.change_test_button)

        panel_layout.addWidget(controls_widget)

        return panel

    def _update_time_displays(self):
        """Update mission timer and clock displays"""
        # Update current time (wall clock)
        current_time = datetime.now().strftime("%H:%M:%S")
        self.clock_label.setText(current_time)

        # Update mission elapsed time
        if self.playback_mode:
            # In playback mode, use playback_time (controlled by timeline seek)
            self._update_mission_time_label(self.playback_time)
            # Don't auto-update timeline (user controls it via seek slider)
        elif self.mission_running and self.mission_start_time:
            # In live mode, use actual elapsed time
            elapsed = datetime.now() - self.mission_start_time
            total_seconds = elapsed.total_seconds()
            self._update_mission_time_label(total_seconds)
            # Update timeline with current time
            self.timeline.set_current_time(total_seconds)
        else:
            # Show T+00:00:00.000000 when not running
            self._update_mission_time_label(0.0)
            if not self.playback_mode:
                self.timeline.set_current_time(0.0)

    def _update_mission_time_label(self, total_seconds):
        """Update the mission time label with given time in seconds"""
        abs_seconds = abs(total_seconds)
        hours = int(abs_seconds // 3600)
        minutes = int((abs_seconds % 3600) // 60)
        seconds = int(abs_seconds % 60)
        microseconds = int((abs_seconds % 1) * 1e6)
        sign = "+" if total_seconds >= 0 else "-"
        self.mission_time_label.setText(f"T{sign}{hours:02d}:{minutes:02d}:{seconds:02d}.{microseconds:06d}")

    def _on_start_clicked(self):
        """Handle START button click"""
        self.log.info("START button clicked - Mission started")
        # Start mission timer
        self.mission_start_time = datetime.now()
        self.mission_running = True
        # TODO: Implement start logic
        pass

    def _on_soft_stop_clicked(self):
        """Handle SOFT STOP button click"""
        self.log.info("SOFT STOP button clicked")
        # Stop mission timer
        self.mission_running = False
        # TODO: Implement soft stop logic (sequential shutdown)
        pass

    def _on_hard_stop_clicked(self):
        """Handle HARD STOP button click"""
        self.log.info("HARD STOP button clicked - EMERGENCY STOP")
        # Stop mission timer immediately
        self.mission_running = False
        # TODO: Implement hard stop logic (immediate shutdown like physical button)
        pass

    def _on_change_test_clicked(self):
        """Handle CHANGE TEST button click (playback mode only)"""
        self.log.info("CHANGE TEST button clicked - Returning to test selection")
        self.change_test_requested = True
        self.close()  # Close the window to return to test selection

    def _on_timeline_seek(self, seek_time):
        """Handle timeline seek request (playback mode only)"""
        self.playback_time = seek_time
        self.timeline.set_current_time(seek_time)
        self._update_mission_time_label(seek_time)
        sign = "+" if seek_time >= 0 else ""
        self.log.debug(f"Playback seeked to T{sign}{seek_time:.2f}s")

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