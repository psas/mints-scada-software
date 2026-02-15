# controller_window.py
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QTimer

import qdarkstyle
import logging
from datetime import datetime

from gui import ListView, GraphView, ExportView, ConsoleView, ScriptView, MintsScriptAPI, AutoPollerRow
from gui.timelineview import TimelineView
from nexus import BusRider


class ControllerWindow(QMainWindow):
    STATUS_STYLE = {
        "idle":   ("Idle",   "#616161", "#ffffff"),
        "normal": ("Normal", "#2e7d32", "#ffffff"),
        "hold":   ("Hold",   "#1565C0", "#ffffff"),
        "abort":  ("Abort",  "#EF6C00", "#ffffff"),
        "estop":  ("E-Stop", "#C62828", "#ffffff"),
    }
    HEALTH_STYLE = {
        "default":   ("--",        "#616161", "#ffffff"),
        "ok":        ("OK",        "#2e7d32", "#ffffff"),
        "attention": ("Attention", "#F9A825", "#000000"),
        "alarm":     ("Alarm",     "#C62828", "#ffffff"),
    }
    MODE_STYLE = {
        "auto":     ("Auto",     "#EF6C00", "#ffffff"),
        "manual":   ("Manual",   "#EF6C00", "#ffffff"),
        "playback": ("Playback", "#1565C0", "#ffffff"),
    }
    SCRIPT_STYLE = {
        "idle":    ("Idle",    "#616161", "#ffffff"),
        "running": ("Running", "#EF6C00", "#ffffff"),
        "pause":   ("Paused",  "#1565C0", "#ffffff"),
    }

    def __init__(self, loghandler=None, autopoller=None, playback_mode=False, test_name=None, manager=None):
        super().__init__()
        self.manager = manager

        logging.getLogger("qdarkstyle").setLevel(logging.ERROR)
        self.log = logging.getLogger("controller_window")

        self.autopoller = autopoller
        self.playback_mode = playback_mode
        self.test_name = test_name

        self.devices: dict[str, BusRider] = {}

        self.mission_start_time = None
        self.mission_running = False
        self.playback_time = 0.0

        self.setWindowTitle("minTS Controller - Left Screen")

        QApplication.setStyle("Fusion")
        self.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyqt5"))
        self.setFont(QFont("Arial", 10))

        # ====== Application widgets ======
        self.timeline = TimelineView(
            playback_mode=self.playback_mode,
            show_event_columns=False,  # Do not show Prev/Current/Next columns in the timeline
            embedded=True,             # Outer container controls background
        )

        # Note: connect signals only after self.timeline is created
        self.timeline.stage_changed.connect(self.set_stages)

        if self.playback_mode:
            self.timeline.seek_requested.connect(self._on_timeline_seek)

        self.graph = GraphView()
        self.listtab = ListView()
        self.console = ConsoleView(loghandler)
        self.exporter = ExportView()
        self.scripter = ScriptView(
            MintsScriptAPI(
                devices=self.devices,
                graph=self.graph,
                exporter=self.exporter,
                autopoller=self.autopoller,
                abort=self.abort,
            )
        )

        # ====== UI ======
        central = QWidget()
        self.setCentralWidget(central)

        # Key: set the main background to a light color to avoid qdarkstyle turning blank areas black
        central.setStyleSheet("background:#e0e0e0;")

        self.mainlayout = QVBoxLayout(central)
        self.mainlayout.setSpacing(0)
        self.mainlayout.setContentsMargins(0, 0, 0, 0)

        self.mainlayout.addWidget(self._create_header_bar())
        self.mainlayout.addWidget(self._create_timeline_bar())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setSpacing(8)
        body_layout.setContentsMargins(8, 8, 8, 8)

        body_layout.addWidget(self._create_left_main_area(), 1)
        body_layout.addWidget(self._create_right_controller_area(), 0)
        self.mainlayout.addWidget(body, 1)

        if self.autopoller is not None:
            apr = AutoPollerRow(self.autopoller)
            self.mainlayout.addLayout(apr)

        # ====== Timers ======
        self.display_timer = QTimer(self)
        self.display_timer.timeout.connect(self._update_time_displays)
        self.display_timer.start(100)

        # Initial state
        self.set_status("idle" if not self.playback_mode else "hold")
        self.set_health("default" if not self.playback_mode else "ok")
        self.set_mode("playback" if self.playback_mode else "auto")
        self.set_script_state("idle" if not self.playback_mode else "pause")
        self.set_stages("Prev", "Current", "Next")

    def closeEvent(self, event):
        if self.manager:
            self.manager.close_all()
        event.accept()

    # =========================================================
    # Header Bar (avoid qdarkstyle "dark blocks" behind text)
    # =========================================================
    def _create_header_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("headerBar")
        bar.setStyleSheet(
            """
            QFrame#headerBar{
                background:#d0d0d0;
                border:0px;
            }
            /* Key: make all children transparent so qdarkstyle won't apply dark label backgrounds */
            QFrame#headerBar QWidget{
                background: transparent;
                border: 0px;
            }
            QFrame#headerBar QLabel{
                background: transparent;
                border: none;
            }
        """
        )

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(10)

        title = QLabel("minTS SCADA Controller")
        title.setFont(QFont("Arial", 20, QFont.Bold))
        title.setStyleSheet("color:#111; background: transparent; border: none;")
        lay.addWidget(title, 0, Qt.AlignVCenter)

        stages = QWidget()
        slay = QHBoxLayout(stages)
        slay.setContentsMargins(0, 0, 0, 0)
        slay.setSpacing(6)

        self.stage_prev = self._make_stage_box("Prev")
        self.stage_curr = self._make_stage_box("Current")
        self.stage_next = self._make_stage_box("Next")

        slay.addWidget(self.stage_prev)
        slay.addWidget(self.stage_curr)
        slay.addWidget(self.stage_next)
        lay.addWidget(stages, 0, Qt.AlignVCenter)

        lay.addStretch(1)

        self.mission_time_label = QLabel("T+00:00:00.000")
        self.mission_time_label.setFont(QFont("Courier New", 22, QFont.Bold))
        self.mission_time_label.setStyleSheet("color:#21c45a; padding:0 12px; background: transparent; border:none;")
        self.mission_time_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.mission_time_label, 0, Qt.AlignVCenter)

        lay.addStretch(1)

        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.setSpacing(4)

        row1 = QWidget()
        row1_lay = QHBoxLayout(row1)
        row1_lay.setContentsMargins(0, 0, 0, 0)
        row1_lay.setSpacing(10)

        status_label = QLabel("Status:")
        status_label.setFont(QFont("Arial", 18, QFont.Bold))
        status_label.setStyleSheet("color:#111; background: transparent; border:none;")
        row1_lay.addWidget(status_label)

        self.status_badge = QLabel("Idle")
        self._set_badge(self.status_badge, "Idle", "#616161", "#ffffff", big=True)
        row1_lay.addWidget(self.status_badge)

        row1_lay.addSpacing(16)

        health_label = QLabel("Health:")
        health_label.setFont(QFont("Arial", 18, QFont.Bold))
        health_label.setStyleSheet("color:#111; background: transparent; border:none;")
        row1_lay.addWidget(health_label)

        self.health_badge = QLabel("--")
        self._set_badge(self.health_badge, "--", "#616161", "#ffffff", big=True)
        row1_lay.addWidget(self.health_badge)

        row1_lay.addStretch(1)
        rlay.addWidget(row1)

        row2 = QWidget()
        row2_lay = QHBoxLayout(row2)
        row2_lay.setContentsMargins(0, 0, 0, 0)
        row2_lay.setSpacing(8)

        mode_label = QLabel("Mode:")
        mode_label.setFont(QFont("Arial", 12, QFont.Bold))
        mode_label.setStyleSheet("color:#111; background: transparent; border:none;")
        row2_lay.addWidget(mode_label)

        self.mode_badge = QLabel("Auto")
        self._set_badge(self.mode_badge, "Auto", "#EF6C00", "#ffffff", big=False)
        row2_lay.addWidget(self.mode_badge)

        script_label = QLabel("Script:")
        script_label.setFont(QFont("Arial", 12, QFont.Bold))
        script_label.setStyleSheet("color:#111; background: transparent; border:none;")
        row2_lay.addWidget(script_label)

        self.script_badge = QLabel("Idle")
        self._set_badge(self.script_badge, "Idle", "#616161", "#ffffff", big=False)
        row2_lay.addWidget(self.script_badge)

        row2_lay.addStretch(1)

        self.clock_label = QLabel("00:00:00")
        self.clock_label.setFont(QFont("Courier New", 12))
        self.clock_label.setStyleSheet("color:#333; background: transparent; border:none;")
        row2_lay.addWidget(self.clock_label)

        rlay.addWidget(row2)

        lay.addWidget(right, 0, Qt.AlignVCenter)
        return bar

    def _make_stage_box(self, title: str) -> QWidget:
        box = QFrame()
        box.setFixedSize(130, 48)
        box.setStyleSheet(
            """
            QFrame{
                background:#bdbdbd;
                border-radius:8px;
                border:1px solid #9e9e9e;
            }
        """
        )
        v = QVBoxLayout(box)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(0)

        t = QLabel(title)
        t.setFont(QFont("Arial", 9, QFont.Bold))
        t.setStyleSheet("color:#222; background: transparent; border: none;")
        v.addWidget(t)

        val = QLabel("(placeholder)")
        val.setFont(QFont("Arial", 10))
        val.setStyleSheet("color:#111; background: transparent; border: none;")
        v.addWidget(val)

        box._value_label = val
        return box

    # =========================================================
    # Timeline Bar (neutral background; timeline is embedded/transparent)
    # =========================================================
    def _create_timeline_bar(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("timelineBar")
        frame.setStyleSheet(
            """
            QFrame#timelineBar{
                background:#2a2d2f; /* neutral and less distracting */
                border:0px;
            }
        """
        )

        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(0)

        self.timeline.setStyleSheet("background: transparent; border:none;")
        self.timeline.setMinimumHeight(56)
        self.timeline.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay.addWidget(self.timeline)
        return frame

    # =========================================================
    # Body layout (keep your current layout)
    # =========================================================
    def _create_left_main_area(self) -> QWidget:
        # Left: Devices (listtab)  Right: Main/Grid (graph)
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(3)
        split.setChildrenCollapsible(False)

        dev_panel = self._panel("Devices", self.listtab)
        dev_panel.setMinimumWidth(260)
        split.addWidget(dev_panel)

        graph_panel = self._panel("Main View", self.graph)
        split.addWidget(graph_panel)

        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)

        split.setSizes([320, 1000])
        return split

    def _create_right_controller_area(self) -> QWidget:
        outer = QWidget()
        outer_layout = QHBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(8)

        left_stack = QSplitter(Qt.Vertical)
        left_stack.setHandleWidth(2)
        left_stack.addWidget(self._panel("Logs", self.console))
        left_stack.addWidget(self._panel("Script Control", self.scripter))
        left_stack.addWidget(self._panel("Telemetry (Placeholder)", QLabel("Placeholder")))
        left_stack.setSizes([520, 260, 240])

        btn_col = QFrame()
        btn_col.setFixedWidth(170)
        btn_col.setStyleSheet("QFrame{background:#cfcfcf; border-radius:10px; border:1px solid #9e9e9e;}")
        blay = QVBoxLayout(btn_col)
        blay.setContentsMargins(12, 12, 12, 12)
        blay.setSpacing(12)

        self.btn_continue = QPushButton("Continue")
        self.btn_continue.setMinimumHeight(76)
        self.btn_continue.setStyleSheet(self._btn_purple())
        self.btn_continue.clicked.connect(self._on_continue_clicked)
        blay.addWidget(self.btn_continue)

        self.btn_hold = QPushButton("Hold")
        self.btn_hold.setMinimumHeight(76)
        self.btn_hold.setStyleSheet(self._btn_purple())
        self.btn_hold.clicked.connect(self._on_hold_clicked)
        blay.addWidget(self.btn_hold)

        self.btn_abort = QPushButton("Abort")
        self.btn_abort.setMinimumHeight(76)
        self.btn_abort.setStyleSheet(self._btn_purple())
        self.btn_abort.clicked.connect(self._on_abort_clicked)
        blay.addWidget(self.btn_abort)

        self.btn_manual_auto = QPushButton("Manual/Auto")
        self.btn_manual_auto.setMinimumHeight(76)
        self.btn_manual_auto.setStyleSheet(self._btn_purple())
        self.btn_manual_auto.clicked.connect(self._on_manual_auto_clicked)
        blay.addWidget(self.btn_manual_auto)

        blay.addStretch(1)

        outer_layout.addWidget(left_stack, 1)
        outer_layout.addWidget(btn_col, 0)
        return outer

    def _panel(self, title: str, widget: QWidget) -> QWidget:
        panel = QFrame()
        panel.setStyleSheet("QFrame{background:#202020; border:1px solid #444; border-radius:10px;}")
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        head = QLabel(title)
        head.setStyleSheet(
            """
            QLabel{
                background:#2a2a2a;
                color:#fff;
                padding:10px;
                border-top-left-radius:10px;
                border-top-right-radius:10px;
                font-weight:bold;
            }
        """
        )
        v.addWidget(head)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(10, 10, 10, 10)
        bl.addWidget(widget)
        v.addWidget(body, 1)
        return panel

    # =========================================================
    # Badge / Styles
    # =========================================================
    def _set_badge(self, label: QLabel, text: str, bg: str, fg: str, big: bool):
        label.setText(text)
        pad = "6px 12px" if big else "4px 10px"
        fs = "18px" if big else "12px"
        label.setStyleSheet(
            f"""
            QLabel {{
                background: {bg};
                color: {fg};
                padding: {pad};
                border-radius: 10px;
                font-size: {fs};
                font-weight: 800;
            }}
        """
        )

    def _btn_purple(self) -> str:
        return """
            QPushButton{
                background:#8e24aa;
                color:white;
                border:none;
                border-radius:10px;
                font-size:16px;
                font-weight:800;
            }
            QPushButton:hover{ background:#7b1fa2; }
            QPushButton:pressed{ background:#6a1b9a; }
            QPushButton:disabled{ background:#555; color:#bbb; }
        """

    # =========================================================
    # Public setters
    # =========================================================
    def set_status(self, key: str):
        text, bg, fg = self.STATUS_STYLE.get(key.lower().strip(), self.STATUS_STYLE["idle"])
        self._set_badge(self.status_badge, text, bg, fg, big=True)

    def set_health(self, key: str):
        text, bg, fg = self.HEALTH_STYLE.get(key.lower().strip(), self.HEALTH_STYLE["default"])
        self._set_badge(self.health_badge, text, bg, fg, big=True)

    def set_mode(self, key: str):
        text, bg, fg = self.MODE_STYLE.get(key.lower().strip(), self.MODE_STYLE["auto"])
        self._set_badge(self.mode_badge, text, bg, fg, big=False)

    def set_script_state(self, key: str):
        text, bg, fg = self.SCRIPT_STYLE.get(key.lower().strip(), self.SCRIPT_STYLE["idle"])
        self._set_badge(self.script_badge, text, bg, fg, big=False)

    def set_stages(self, prev: str, current: str, next_: str):
        self.stage_prev._value_label.setText(prev)
        self.stage_curr._value_label.setText(current)
        self.stage_next._value_label.setText(next_)

    # =========================================================
    # Timer update
    # =========================================================
    def _update_time_displays(self):
        self.clock_label.setText(datetime.now().strftime("%H:%M:%S"))

        if self.playback_mode:
            self._update_mission_time_label(self.playback_time)
        elif self.mission_running and self.mission_start_time:
            elapsed = datetime.now() - self.mission_start_time
            total_seconds = elapsed.total_seconds()
            self._update_mission_time_label(total_seconds)
            self.timeline.set_current_time(total_seconds)
        else:
            self._update_mission_time_label(0.0)
            if not self.playback_mode:
                self.timeline.set_current_time(0.0)

    def _update_mission_time_label(self, total_seconds: float):
        abs_seconds = abs(total_seconds)
        hours = int(abs_seconds // 3600)
        minutes = int((abs_seconds % 3600) // 60)
        seconds = int(abs_seconds % 60)
        milliseconds = int((abs_seconds % 1) * 1000)
        sign = "+" if total_seconds >= 0 else "-"
        self.mission_time_label.setText(f"T{sign}{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}")

    def _on_timeline_seek(self, seek_time: float):
        self.playback_time = seek_time
        self.timeline.set_current_time(seek_time)
        self._update_mission_time_label(seek_time)

    # =========================================================
    # Buttons (placeholder behavior)
    # =========================================================
    def _on_continue_clicked(self):
        self.set_status("normal")
        self.set_script_state("running")

    def _on_hold_clicked(self):
        self.set_status("hold")
        self.set_script_state("pause")

    def _on_abort_clicked(self):
        self.set_status("abort")
        self.set_script_state("pause")
        self.abort()

    def _on_manual_auto_clicked(self):
        cur = self.mode_badge.text().lower()
        self.set_mode("manual" if cur == "auto" else "auto")

    # =========================================================
    # Device hooks
    # =========================================================
    def addDevice(self, device: BusRider, display: QWidget = None):
        self.devices[device.name] = device
        self.exporter.devices.append(device)
        if display is not None:
            self.listtab.layout.addLayout(display)
        self.graph.addSensor(device, display is not None)

    def abort(self):
        self.log.fatal("Abort triggered! Slap the big red button NOW!")