# controller_window.py
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont, QPainter, QPen, QColor
from PyQt5.QtCore import Qt, QTimer, QRect, pyqtSignal

import qdarkstyle
import logging
import math
from datetime import datetime

from gui import ListView, GraphView, ExportView, ConsoleView, ScriptView, MintsScriptAPI, AutoPollerRow
from gui.timelineview import TimelineView
from nexus import BusRider


class EngineForceWidget(QWidget):
    """
    Four-sensor engine thrust visualizer.

    - Total thrust is shown in blue at the top-left.
      Total is shown only when ALL four sensors are present; otherwise it shows "-- N".
    - Four sensor readings are shown around the circle: Up / Right / Down / Left.
      Missing sensor values are shown as:
          --
          N
    - The dot shows whether thrust is centered:
        dx = (Right - Left) / Total
        dy = (Up - Down) / Total
      If any sensor is missing (or Total is ~0), the dot stays centered and is drawn gray.
    """

    def __init__(self, parent=None, dot_gain=0.92):
        super().__init__(parent)

        self.up_n = None
        self.right_n = None
        self.down_n = None
        self.left_n = None

        self.dot_gain = float(dot_gain)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(200)

    def set_sensors(self, up=None, right=None, down=None, left=None):
        self.up_n = None if up is None else float(up)
        self.right_n = None if right is None else float(right)
        self.down_n = None if down is None else float(down)
        self.left_n = None if left is None else float(left)
        self.update()

    @staticmethod
    def _clamp(v, lo, hi):
        return lo if v < lo else hi if v > hi else v

    def _sum_available(self):
        vals = [self.up_n, self.right_n, self.down_n, self.left_n]
        return sum(v for v in vals if v is not None)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        base = max(1.0, min(w, h))

        pad = self._clamp(base * 0.03, 6.0, 16.0)
        gap = self._clamp(base * 0.025, 6.0, 14.0)

        total_fs = int(self._clamp(base * 0.09, 14.0, 30.0))
        val_fs = int(self._clamp(base * 0.065, 10.0, 20.0))
        unit_fs = int(self._clamp(val_fs * 0.80, 8.0, 16.0))

        circle_pen_w = int(self._clamp(base * 0.012, 2.0, 5.0))
        dot_r = int(self._clamp(base * 0.022, 6.0, 12.0))
        center_r = int(self._clamp(base * 0.015, 4.0, 8.0))

        box_w = self._clamp(base * 0.18, 52.0, 92.0)
        box_h = self._clamp(base * 0.13, 34.0, 52.0)

        p.fillRect(0, 0, w, h, QColor(0, 0, 0, 0))

        all_present = (
            self.up_n is not None and self.right_n is not None and
            self.down_n is not None and self.left_n is not None
        )

        # --- Total (pinned top-left) ---
        total_font = QFont("Arial", total_fs, QFont.Bold)
        p.setFont(total_font)
        p.setPen(QColor("#66aaff"))

        total_rect_h = int(total_fs * 1.6)
        total_rect = QRect(int(pad), int(pad), int(w * 0.6), total_rect_h)

        if all_present:
            total = self._sum_available()
            total_text = f"{total:.1f} N"
        else:
            total = 0.0  # keep a numeric fallback for dot logic
            total_text = "-- N"

        p.drawText(total_rect, Qt.AlignLeft | Qt.AlignVCenter, total_text)

        top_area = int(pad + total_rect_h + pad * 0.4)

        # --- Compute circle radius ---
        max_radius_x = (w - 2.0 * (box_w + gap + pad)) / 2.0
        max_radius_y = (h - top_area - 2.0 * (box_h + gap) - pad) / 2.0
        radius = min(max_radius_x, max_radius_y)
        radius = max(40.0, radius)

        used_h = (box_h + gap) + (2.0 * radius) + (box_h + gap)
        avail_h = max(0.0, (h - top_area) - pad)
        y_offset = (avail_h - used_h) * 0.5
        if y_offset < 0:
            y_offset = 0.0

        cx = w * 0.5
        cy = top_area + y_offset + (box_h + gap) + radius

        # --- Draw circle ---
        p.setPen(QPen(QColor("#d0d0d0"), circle_pen_w))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2))

        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#bfbfbf"))
        p.drawEllipse(int(cx - center_r), int(cy - center_r), int(center_r * 2), int(center_r * 2))

        # --- Draw sensor boxes (two-line: value / N) ---
        val_font = QFont("Arial", val_fs, QFont.Bold)
        unit_font = QFont("Arial", unit_fs, QFont.Bold)
        p.setPen(QColor("#e0e0e0"))

        def draw_value_box(x, y, v):
            rect = QRect(int(x), int(y), int(box_w), int(box_h))
            upper = QRect(rect.x(), rect.y(), rect.width(), rect.height() // 2)
            lower = QRect(rect.x(), rect.y() + rect.height() // 2, rect.width(), rect.height() - rect.height() // 2)

            p.setFont(val_font)
            if v is None:
                p.drawText(upper, Qt.AlignCenter, "--")
            else:
                p.drawText(upper, Qt.AlignCenter, f"{v:.1f}")

            p.setFont(unit_font)
            p.drawText(lower, Qt.AlignCenter, "N")

        up_x = cx - box_w / 2.0
        up_y = cy - radius - gap - box_h

        down_x = cx - box_w / 2.0
        down_y = cy + radius + gap

        left_x = cx - radius - gap - box_w
        left_y = cy - box_h / 2.0

        right_x = cx + radius + gap
        right_y = cy - box_h / 2.0

        def nudge_into_view(x, y):
            nx = x
            ny = y
            if nx < pad:
                nx = pad
            if nx + box_w > w - pad:
                nx = w - pad - box_w
            if ny < top_area:
                ny = top_area
            if ny + box_h > h - pad:
                ny = h - pad - box_h
            return nx, ny

        up_x, up_y = nudge_into_view(up_x, up_y)
        right_x, right_y = nudge_into_view(right_x, right_y)
        down_x, down_y = nudge_into_view(down_x, down_y)
        left_x, left_y = nudge_into_view(left_x, left_y)

        draw_value_box(up_x, up_y, self.up_n)
        draw_value_box(right_x, right_y, self.right_n)
        draw_value_box(down_x, down_y, self.down_n)
        draw_value_box(left_x, left_y, self.left_n)

        # --- Dot (imbalance) ---
        eps = 1e-6
        if all_present and total > eps:
            dx = (self.right_n - self.left_n) / total
            dy = (self.up_n - self.down_n) / total
            dot_color = QColor("#d32f2f")
        else:
            dx = 0.0
            dy = 0.0
            dot_color = QColor("#888888")

        mag = math.hypot(dx, dy)
        if mag > 1.0:
            dx /= mag
            dy /= mag

        dot_x = cx + dx * radius * self.dot_gain
        dot_y = cy - dy * radius * self.dot_gain

        p.setBrush(dot_color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(int(dot_x - dot_r), int(dot_y - dot_r), int(dot_r * 2), int(dot_r * 2))

        p.end()


# =========================================================
# Fuel Capacity widgets (Tanks)
# =========================================================
class TankGaugeWidget(QWidget):
    """
    Single tank gauge:
    - 4 lines of text on top (pressure/temp/level/valve)
    - tank rectangle with fill
    - label at bottom (IPA/LOX)
    - emits clicked(name) when pressed
    """
    clicked = pyqtSignal(str)

    def __init__(self, name: str, fill_color: str, parent=None):
        super().__init__(parent)
        self.name = name
        self.fill_color = QColor(fill_color)

        self.pressure_psi = None
        self.temp_c = None
        self.level_pct = None
        self.valve_open_pct = None

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(220)
        self.setCursor(Qt.PointingHandCursor)

    def set_data(self, pressure_psi=None, temp_c=None, level_pct=None, valve_open_pct=None):
        self.pressure_psi = None if pressure_psi is None else float(pressure_psi)
        self.temp_c = None if temp_c is None else float(temp_c)
        self.level_pct = None if level_pct is None else float(level_pct)
        self.valve_open_pct = None if valve_open_pct is None else float(valve_open_pct)
        self.update()

    @staticmethod
    def _clamp(v, lo, hi):
        return lo if v < lo else hi if v > hi else v

    @staticmethod
    def _fmt_num(v, digits0=True):
        if v is None:
            return "--"
        return f"{v:.0f}" if digits0 else f"{v:.1f}"

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.name)
        super().mousePressEvent(e)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        base = max(1.0, min(w, h))

        pad = self._clamp(base * 0.06, 8.0, 16.0)
        line_gap = self._clamp(base * 0.015, 2.0, 6.0)

        txt_fs = int(self._clamp(base * 0.085, 10.0, 15.0))
        label_fs = int(self._clamp(base * 0.10, 12.0, 18.0))

        txt_font = QFont("Arial", txt_fs, QFont.DemiBold)
        label_font = QFont("Arial", label_fs, QFont.Bold)

        p.fillRect(0, 0, w, h, QColor(0, 0, 0, 0))

        # ---- Top 4 lines ----
        p.setFont(txt_font)
        p.setPen(QColor("#e6e6e6"))

        # Missing data displays as: "-- <unit>"
        # Standard unit formatting: psi, °C, %


        lines = [
            f"Pres: {self._fmt_num(self.pressure_psi)} psi",
            f"Temp: {self._fmt_num(self.temp_c)} °C",
            f"Flow: {self._fmt_num(self.valve_open_pct)} %",
            f"Level: {self._fmt_num(self.level_pct)} %",
        ]

        fm = p.fontMetrics()
        line_h = fm.height()
        text_block_h = line_h * 4 + line_gap * 3

        y = pad
        for i, s in enumerate(lines):
            r = QRect(int(pad), int(y), int(w - 2 * pad), int(line_h))
            p.drawText(r, Qt.AlignHCenter | Qt.AlignVCenter, s)
            y += line_h + (line_gap if i < 3 else 0)

        # ---- Label area ----
        p.setFont(label_font)
        label_h = p.fontMetrics().height()

        # ---- Tank geometry ----
        tank_top = pad + text_block_h + pad * 0.35
        tank_bottom = h - pad - label_h - pad * 0.25
        tank_h = max(80.0, tank_bottom - tank_top)

        tank_w = min(w - 2 * pad, tank_h * 0.38)
        tank_w = max(42.0, tank_w)

        tank_x = (w - tank_w) * 0.5
        tank_y = tank_top

        # ---- Draw tank body ----
        border_w = int(self._clamp(base * 0.012, 2.0, 4.0))
        p.setPen(QPen(QColor("#cfcfcf"), border_w))
        p.setBrush(QColor("#f2f2f2"))
        p.drawRect(int(tank_x), int(tank_y), int(tank_w), int(tank_h))

        # ---- Fill ----
        inner_pad = border_w + 1
        inner = QRect(
            int(tank_x + inner_pad),
            int(tank_y + inner_pad),
            int(tank_w - 2 * inner_pad),
            int(tank_h - 2 * inner_pad),
        )

        lvl = self.level_pct
        if lvl is None:
            # No data -> treat fill as 0% internally
            lvl = 0.0
            fill_color = QColor("#444444")
        else:
            lvl = self._clamp(lvl, 0.0, 100.0)
            fill_color = self.fill_color

        fill_h = int(inner.height() * (lvl / 100.0))
        fill_rect = QRect(inner.x(), inner.y() + inner.height() - fill_h, inner.width(), fill_h)

        p.setPen(Qt.NoPen)
        p.setBrush(fill_color)
        p.drawRect(fill_rect)

        # ---- Bottom label ----
        p.setFont(label_font)
        p.setPen(QColor("#e6e6e6"))
        label_rect = QRect(int(pad), int(h - pad - label_h), int(w - 2 * pad), int(label_h))
        p.drawText(label_rect, Qt.AlignHCenter | Qt.AlignVCenter, self.name)

        p.end()


class TelemetryWidget(QWidget):
    """
    Two-tank telemetry panel (IPA + LOX) with an info label below.
    Clicking a tank updates info text and emits tank_clicked(name).
    """
    tank_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.ipa = TankGaugeWidget("IPA", "#ff1e1e")
        self.lox = TankGaugeWidget("LOX", "#3b22ff")

        self.info_label = QLabel("--")
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color:#cfcfcf; font-weight:600;")

        row = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(18)
        row_lay.addWidget(self.ipa, 1)
        row_lay.addWidget(self.lox, 1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(row, 1)
        lay.addWidget(self.info_label, 0)

        self.ipa.clicked.connect(self._on_tank_clicked)
        self.lox.clicked.connect(self._on_tank_clicked)

        # Default state: no data (shows "-- <unit>" and level fill defaults to 0%)
        self.set_ipa()
        self.set_lox()

    def _on_tank_clicked(self, name: str):
        self.info_label.setText(f"{name} tank selected.")
        self.tank_clicked.emit(name)

    def set_ipa(self, pressure_psi=None, temp_c=None, level_pct=None, valve_open_pct=None):
        self.ipa.set_data(pressure_psi, temp_c, level_pct, valve_open_pct)

    def set_lox(self, pressure_psi=None, temp_c=None, level_pct=None, valve_open_pct=None):
        self.lox.set_data(pressure_psi, temp_c, level_pct, valve_open_pct)

    def set_info(self, text: str):
        self.info_label.setText(text)


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
            show_event_columns=False,
            embedded=True,
        )
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

        # Engine force widget
        self.engine_force_widget = EngineForceWidget(dot_gain=0.90)
        self.engine_force_widget.set_sensors(None, None, None, None)

        # Telemetry widget
        self.telemetry_widget = TelemetryWidget()
        self.telemetry_widget.tank_clicked.connect(self._on_tank_clicked)

        # ====== UI ======
        central = QWidget()
        self.setCentralWidget(central)
        central.setStyleSheet("background:#121212;")

        self.mainlayout = QVBoxLayout(central)
        self.mainlayout.setSpacing(0)
        self.mainlayout.setContentsMargins(0, 0, 0, 0)

        self.mainlayout.addWidget(self._create_header_bar())
        self.mainlayout.addWidget(self._create_timeline_bar())

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        body_layout = QHBoxLayout(body)
        body_layout.setSpacing(0)
        body_layout.setContentsMargins(8, 8, 8, 8)

        # Make the LEFT main window area and the RIGHT (Logs/controls) column draggable
        body_split = QSplitter(Qt.Horizontal)
        body_split.setHandleWidth(4)
        body_split.setChildrenCollapsible(False)
        body_split.setOpaqueResize(True)

        body_split.setStyleSheet("""
            QSplitter::handle {
                background: #3a3a3a;
            }
            QSplitter::handle:hover {
                background: #5a5a5a;
            }
        """)

        left_area = self._create_left_main_area()
        right_area = self._create_right_controller_area()

        body_split.addWidget(left_area)
        body_split.addWidget(right_area)

        body_split.setStretchFactor(0, 3)
        body_split.setStretchFactor(1, 2)
        body_split.setSizes([1200, 800])

        body_layout.addWidget(body_split, 1)
        self.mainlayout.addWidget(body, 1)


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
    # Header Bar
    # =========================================================
    def _create_header_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("headerBar")
        bar.setStyleSheet(
            """
            QFrame#headerBar{
                background:#151515;
                border:0px;
            }
            QFrame#headerBar QWidget{
                background: transparent;
                border: 0px;
            }
            QFrame#headerBar QLabel{
                background: transparent;
                border: none;
                color: #eaeaea;
            }
        """
        )

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(10)

        title = QLabel("minTS SCADA Controller")
        title.setFont(QFont("Arial", 20, QFont.Bold))
        title.setStyleSheet("color:#f5f5f5; background: transparent; border: none;")
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
        status_label.setStyleSheet("color:#eaeaea; background: transparent; border:none;")
        row1_lay.addWidget(status_label)

        self.status_badge = QLabel("Idle")
        self._set_badge(self.status_badge, "Idle", "#616161", "#ffffff", big=True)
        row1_lay.addWidget(self.status_badge)

        row1_lay.addSpacing(16)

        health_label = QLabel("Health:")
        health_label.setFont(QFont("Arial", 18, QFont.Bold))
        health_label.setStyleSheet("color:#eaeaea; background: transparent; border:none;")
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
        mode_label.setStyleSheet("color:#eaeaea; background: transparent; border:none;")
        row2_lay.addWidget(mode_label)

        self.mode_badge = QLabel("Auto")
        self._set_badge(self.mode_badge, "Auto", "#EF6C00", "#ffffff", big=False)
        row2_lay.addWidget(self.mode_badge)

        script_label = QLabel("Script:")
        script_label.setFont(QFont("Arial", 12, QFont.Bold))
        script_label.setStyleSheet("color:#eaeaea; background: transparent; border:none;")
        row2_lay.addWidget(script_label)

        self.script_badge = QLabel("Idle")
        self._set_badge(self.script_badge, "Idle", "#616161", "#ffffff", big=False)
        row2_lay.addWidget(self.script_badge)

        row2_lay.addStretch(1)

        self.clock_label = QLabel("00:00:00")
        self.clock_label.setFont(QFont("Courier New", 12))
        self.clock_label.setStyleSheet("color:#cfcfcf; background: transparent; border:none;")
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
                background:#232323;
                border-radius:8px;
                border:1px solid #555;
            }
        """
        )
        v = QVBoxLayout(box)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(0)

        t = QLabel(title)
        t.setFont(QFont("Arial", 9, QFont.Bold))
        t.setStyleSheet("color:#bdbdbd; background: transparent; border: none;")
        v.addWidget(t)

        val = QLabel("(placeholder)")
        val.setFont(QFont("Arial", 10))
        val.setStyleSheet("color:#ffffff; background: transparent; border: none;")
        v.addWidget(val)

        box._value_label = val
        return box

    # =========================================================
    # Timeline Bar
    # =========================================================
    def _create_timeline_bar(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("timelineBar")
        frame.setStyleSheet(
            """
            QFrame#timelineBar{
                background:#2a2d2f;
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
    # Left area:
    # Devices | Main View (Graph + AutoPollerRow inside)
    # =========================================================
    def _create_left_main_area(self) -> QWidget:
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(3)
        split.setChildrenCollapsible(False)

        dev_panel = self._panel("Devices", self.listtab)
        dev_panel.setMinimumWidth(260)
        split.addWidget(dev_panel)

        main_view = QWidget()
        mv = QVBoxLayout(main_view)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(8)

        mv.addWidget(self.graph, 1)

        if (self.autopoller is not None) and (not self.playback_mode):
            mv.addLayout(AutoPollerRow(self.autopoller))

        graph_panel = self._panel("Main View", main_view)
        split.addWidget(graph_panel)

        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([320, 1000])
        return split

    # =========================================================
    # Right column:
    # - Top: Logs (big)
    # - Bottom row: Fuel Capacity (left) | Script area (right)
    #   Script area split vertically:
    #   - Top: Script Control
    #   - Bottom: Engine Force
    # =========================================================
    def _create_right_controller_area(self) -> QWidget:
        outer = QWidget()
        outer_layout = QHBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(8)

        main_stack = QSplitter(Qt.Vertical)
        main_stack.setHandleWidth(2)
        main_stack.setChildrenCollapsible(False)

        # Top: Logs
        main_stack.addWidget(self._panel("Logs", self.console))

        # Bottom: Fuel Capacity + Script stack
        bottom_row = QSplitter(Qt.Horizontal)
        bottom_row.setHandleWidth(2)
        bottom_row.setChildrenCollapsible(False)

        # Fuel Capacity panel
        bottom_row.addWidget(self._panel("Fuel Capacity", self.telemetry_widget))

        # Script area: top is Script Control, bottom is Engine Force
        script_stack = QSplitter(Qt.Vertical)
        script_stack.setHandleWidth(2)
        script_stack.setChildrenCollapsible(False)

        script_stack.addWidget(self._panel("Script Control", self.scripter))
        script_stack.addWidget(self._panel("Engine Force", self.engine_force_widget))

        # Give the engine widget enough height by default
        script_stack.setSizes([240, 340])

        bottom_row.addWidget(script_stack)

        bottom_row.setStretchFactor(0, 1)
        bottom_row.setStretchFactor(1, 1)
        bottom_row.setSizes([520, 520])

        main_stack.addWidget(bottom_row)
        main_stack.setSizes([620, 380])

        # Button column
        btn_col = QFrame()
        btn_col.setFixedWidth(170)
        btn_col.setStyleSheet("QFrame{background:#1e1e1e; border-radius:10px; border:1px solid #444;}")
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

        outer_layout.addWidget(main_stack, 1)
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
        body.setStyleSheet("background: transparent;")
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

    # Engine force update API
    def set_engine_sensors(self, up=None, right=None, down=None, left=None):
        self.engine_force_widget.set_sensors(up, right, down, left)

    # Telemetry update API
    def set_tank_telemetry(self, tank: str, pressure_psi=None, temp_c=None, level_pct=None, valve_open_pct=None):
        t = (tank or "").strip().lower()
        if t == "ipa":
            self.telemetry_widget.set_ipa(pressure_psi, temp_c, level_pct, valve_open_pct)
        elif t == "lox":
            self.telemetry_widget.set_lox(pressure_psi, temp_c, level_pct, valve_open_pct)

    def set_tank_info(self, text: str):
        self.telemetry_widget.set_info(text)

    def _on_tank_clicked(self, name: str):
        self.set_tank_info(f"{name} tank selected. (put more details here)")

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