from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFrame, QShortcut
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QFont, QPen, QKeySequence
import logging

log = logging.getLogger("timeline")


class TimelineView(QWidget):
    """
    Timeline widget showing T+ time and script events.

    Changes:
    - No longer shows Prev/Current/Next columns (these are shown in the header).
    - Removed Zoom +/- buttons; replaced with keyboard shortcuts (Alt+= / Alt+-).
    - Removed the bottom seek slider (redundant progress bar).
    - When embedded=True, TimelineBar still draws a dark background for readability.
    """

    seek_requested = pyqtSignal(float)          # time in seconds
    stage_changed = pyqtSignal(str, str, str)   # prev, current, next labels

    def __init__(self, playback_mode=False, parent=None, embedded=False, show_event_columns=False):
        super().__init__(parent)
        self.playback_mode = playback_mode
        self.embedded = embedded

        self.current_time = 0.0
        self.total_duration = 0.0
        self.min_time = 0.0
        self.zoom_level = 1.0
        self.events = []

        self._last_stage_tuple = None

        self._setup_ui()
        self._setup_shortcuts()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        container = QFrame()
        if self.embedded:
            container.setStyleSheet("QFrame{background: transparent; border: 0px;}")
        else:
            container.setStyleSheet("QFrame{background:#2a2d2f; border:1px solid #4CAF50;}")

        cl = QVBoxLayout(container)
        cl.setContentsMargins(6, 6, 6, 6)
        cl.setSpacing(0)

        self.timeline_bar = TimelineBar(self)
        self.timeline_bar.setMinimumHeight(60)
        # Let TimelineBar manage its own readable background (even when embedded).
        self.timeline_bar.setStyleSheet("border: 1px solid rgba(255,255,255,0.28);")
        cl.addWidget(self.timeline_bar)

        layout.addWidget(container)

    def _setup_shortcuts(self):
        def bind(seq, fn):
            sc = QShortcut(QKeySequence(seq), self, activated=fn)
            sc.setContext(Qt.ApplicationShortcut)  # Global shortcut (focus-independent)
            return sc

        # Zoom in: Alt + / Alt =
        bind("Alt+=", self.zoom_in)      # Many keyboards produce "+" via Shift+=
        bind("Alt++", self.zoom_in)      # Some systems report it directly
        bind("Alt+Plus", self.zoom_in)   # Qt fallback name

        # Zoom out: Alt -
        bind("Alt+-", self.zoom_out)
        bind("Alt+Minus", self.zoom_out)  # Common Qt name
        bind("Alt+_", self.zoom_out)      # Some keyboards report Alt+Shift+-

    # ---- helpers ----
    def _effective_max_time(self) -> float:
        """
        In live mode total_duration may be 0, so derive an effective max time from current_time.
        """
        return max(self.total_duration, self.current_time, self.min_time + 60.0)

    # ---- public API ----
    def set_current_time(self, time_seconds: float):
        self.current_time = time_seconds
        self._update_event_displays()
        self.timeline_bar.update()

    def set_total_duration(self, duration_seconds: float):
        self.total_duration = duration_seconds
        self.timeline_bar.update()

    def add_event(self, time_seconds: float, label: str):
        self.events.append((time_seconds, label))
        self.events.sort(key=lambda x: x[0])

        if time_seconds < self.min_time:
            self.min_time = time_seconds

        self._update_event_displays()
        self.timeline_bar.update()

    def clear_events(self):
        self.events.clear()
        self.min_time = 0.0
        self._update_event_displays()
        self.timeline_bar.update()

    def zoom_in(self):
        self.zoom_level = min(self.zoom_level * 1.5, 10.0)
        self.timeline_bar._calculate_visible_range()
        self.timeline_bar.update()

    def zoom_out(self):
        self.zoom_level = max(self.zoom_level / 1.5, 1.0)
        self.timeline_bar._calculate_visible_range()
        self.timeline_bar.update()

    # ---- internal ----
    def _update_event_displays(self):
        prev_txt = ""
        curr_txt = ""
        next_txt = ""

        if self.events:
            current_event_idx = None
            for idx, (event_time, _) in enumerate(self.events):
                if event_time <= self.current_time:
                    current_event_idx = idx
                else:
                    break

            prev_event = None
            current_event = None
            next_event = None

            if current_event_idx is not None:
                current_event = self.events[current_event_idx]
                if current_event_idx > 0:
                    prev_event = self.events[current_event_idx - 1]
                if current_event_idx + 1 < len(self.events):
                    next_event = self.events[current_event_idx + 1]
            else:
                next_event = self.events[0]

            prev_txt = prev_event[1] if prev_event else ""
            curr_txt = current_event[1] if current_event else ""
            next_txt = next_event[1] if next_event else ""

        stage_tuple = (prev_txt, curr_txt, next_txt)
        if stage_tuple != self._last_stage_tuple:
            self._last_stage_tuple = stage_tuple
            self.stage_changed.emit(prev_txt, curr_txt, next_txt)


class TimelineBar(QWidget):
    def __init__(self, timeline_view, parent=None):
        super().__init__(parent)
        self.timeline = timeline_view
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

        self.is_dragging = False
        self.drag_visible_start = 0.0
        self.drag_visible_duration = 0.0
        self.last_seek_time = None

        self.scroll_timer = QTimer(self)
        self.scroll_timer.timeout.connect(self._auto_scroll)
        self.scroll_speed = 0.0
        self.edge_threshold = 30

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()

        # Always fill TimelineBar with a dark background for readability (embedded or not).
        painter.fillRect(0, 0, width, height, QColor("#1e1e1e"))

        min_time = self.timeline.min_time
        max_time = self.timeline._effective_max_time()
        time_range = max_time - min_time
        if time_range <= 0:
            time_range = 60.0

        visible_start = self.drag_visible_start
        visible_duration = self.drag_visible_duration

        if visible_duration == 0.0:
            visible_duration = time_range / self.timeline.zoom_level
            visible_start = self.timeline.current_time - (visible_duration / 2)

            if visible_start < min_time:
                visible_start = min_time
            if visible_start + visible_duration > max_time:
                visible_start = max_time - visible_duration

            if visible_duration >= time_range:
                visible_start = min_time
                visible_duration = time_range

            self.drag_visible_start = visible_start
            self.drag_visible_duration = visible_duration

        # Markers
        marker_interval = self._calculate_marker_interval(visible_duration)
        start_marker = int(visible_start / marker_interval) * marker_interval
        num_markers = int((visible_start + visible_duration - start_marker) / marker_interval) + 2

        painter.setPen(QPen(QColor("#555555"), 1))
        painter.setFont(QFont("Arial", 8))

        for i in range(num_markers):
            time_pos = start_marker + i * marker_interval
            if visible_start <= time_pos <= visible_start + visible_duration:
                x = int(((time_pos - visible_start) / visible_duration) * width)
                painter.drawLine(x, height - 15, x, height - 5)

                abs_time = abs(time_pos)
                minutes = int(abs_time // 60)
                seconds = int(abs_time % 60)
                sign = "+" if time_pos >= 0 else "-"
                label = f"T{sign}{minutes}:{seconds:02d}"
                painter.setPen(QColor("#aaaaaa"))
                painter.drawText(x - 20, height - 18, label)
                painter.setPen(QColor("#555555"))

        # T+0 marker
        if visible_start <= 0 <= visible_start + visible_duration:
            x = int((0 - visible_start) / visible_duration * width)
            painter.setPen(QPen(QColor("#FFFFFF"), 2))
            painter.drawLine(x, height - 20, x, height - 5)
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(QFont("Arial", 8, QFont.Bold))
            painter.drawText(x - 15, height - 22, "T+0")

        # Events
        for event_time, event_label in self.timeline.events:
            if visible_start <= event_time <= visible_start + visible_duration:
                x = int(((event_time - visible_start) / visible_duration) * width)
                painter.setPen(QPen(QColor("#FFA726"), 2))
                painter.drawLine(x, 5, x, height - 20)
                painter.setPen(QColor("#FFA726"))
                painter.setFont(QFont("Arial", 8, QFont.Bold))
                painter.drawText(x + 3, 15, event_label)

        # Current time indicator
        if visible_start <= self.timeline.current_time <= visible_start + visible_duration:
            x = int(((self.timeline.current_time - visible_start) / visible_duration) * width)
            painter.setPen(QPen(QColor("#00FF00"), 3))
            painter.drawLine(x, 0, x, height)

        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = True
            if self.drag_visible_duration == 0.0:
                self._calculate_visible_range()
            self._seek_to_position(event.x())

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            x_pos = event.x()
            width = self.width()

            if x_pos < self.edge_threshold:
                distance_from_edge = self.edge_threshold - x_pos
                self.scroll_speed = -distance_from_edge / 10.0
                if not self.scroll_timer.isActive():
                    self.scroll_timer.start(50)
            elif x_pos > width - self.edge_threshold:
                distance_from_edge = x_pos - (width - self.edge_threshold)
                self.scroll_speed = distance_from_edge / 10.0
                if not self.scroll_timer.isActive():
                    self.scroll_timer.start(50)
            else:
                self.scroll_timer.stop()
                self.scroll_speed = 0.0

            self._seek_to_position(x_pos)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = False
            self.scroll_timer.stop()
            self.scroll_speed = 0.0
            self.last_seek_time = None

    def _auto_scroll(self):
        if not self.is_dragging or self.scroll_speed == 0.0:
            return

        min_time = self.timeline.min_time
        max_time = self.timeline._effective_max_time()

        time_per_pixel = self.drag_visible_duration / max(1, self.width())
        time_shift = self.scroll_speed * time_per_pixel

        new_visible_start = self.drag_visible_start + time_shift

        if new_visible_start < min_time:
            new_visible_start = min_time
            self.scroll_timer.stop()
        elif new_visible_start + self.drag_visible_duration > max_time:
            new_visible_start = max_time - self.drag_visible_duration
            self.scroll_timer.stop()

        self.drag_visible_start = new_visible_start

        width = self.width()
        last_mouse_x = self.mapFromGlobal(self.cursor().pos()).x()
        position_ratio = max(0, min(1, last_mouse_x / max(1, width)))
        new_time = self.drag_visible_start + (position_ratio * self.drag_visible_duration)
        new_time = max(min_time, min(new_time, max_time))

        self.timeline.seek_requested.emit(new_time)
        self.update()

    def _calculate_visible_range(self):
        min_time = self.timeline.min_time
        max_time = self.timeline._effective_max_time()
        time_range = max_time - min_time
        if time_range <= 0:
            time_range = 60.0

        visible_duration = time_range / self.timeline.zoom_level
        visible_start = self.timeline.current_time - (visible_duration / 2)

        if visible_start < min_time:
            visible_start = min_time
        if visible_start + visible_duration > max_time:
            visible_start = max_time - visible_duration

        if visible_duration >= time_range:
            visible_start = min_time
            visible_duration = time_range

        self.drag_visible_start = visible_start
        self.drag_visible_duration = visible_duration

    def _seek_to_position(self, x_pos):
        min_time = self.timeline.min_time
        max_time = self.timeline._effective_max_time()

        width = max(1, self.width())
        x_pos = max(0, min(x_pos, width))

        visible_start = self.drag_visible_start
        visible_duration = self.drag_visible_duration

        position_ratio = x_pos / width
        seek_time = visible_start + (position_ratio * visible_duration)
        seek_time = max(min_time, min(seek_time, max_time))

        if self.last_seek_time is None or abs(seek_time - self.last_seek_time) > 0.001:
            self.last_seek_time = seek_time
            self.timeline.seek_requested.emit(seek_time)

    def _calculate_marker_interval(self, visible_duration):
        if visible_duration <= 60:
            return 10
        if visible_duration <= 300:
            return 30
        if visible_duration <= 600:
            return 60
        return 300