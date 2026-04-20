"""gui/timelineview.py

Timeline widgets for live and playback timeline navigation.

This module provides the high-level ``TimelineView`` wrapper used by controller
UI code and the ``TimelineBar`` painting/interaction widget that renders script
event markers, the current playback/live cursor, and seekable time markers.
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFrame, QShortcut
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QFont, QPen, QKeySequence
import logging

log = logging.getLogger("timeline")


class TimelineView(QWidget):
    """Display a zoomable timeline with seek and stage-change signals.

    The view owns timeline state such as the current time, total duration,
    visible event markers, and zoom level. It delegates rendering and pointer
    interaction to ``TimelineBar`` and emits derived previous/current/next event
    labels whenever the active event stage changes.
    """

    seek_requested = pyqtSignal(float)  # time in seconds
    stage_changed = pyqtSignal(str, str, str)  # prev, current, next labels

    def __init__(
        self, playback_mode=False, parent=None, embedded=False, show_event_columns=False
    ):
        """Initialize the timeline view and its child widgets.

        Args:
            playback_mode: Whether the timeline is being used for playback
                scrubbing instead of live display.
            parent: Optional parent widget.
            embedded: Whether the timeline is embedded in another surface that
                already owns most surrounding styling.
            show_event_columns: Unused legacy compatibility argument retained by
                the current constructor signature.
        """
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
        """Build the container layout and timeline bar widget.

        Returns:
            None.
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        container = QFrame()
        if self.embedded:
            container.setStyleSheet("QFrame{background: transparent; border: 0px;}")
        else:
            container.setStyleSheet(
                "QFrame{background:#2a2d2f; border:1px solid #4CAF50;}"
            )

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
        """Register application-wide keyboard shortcuts for timeline zooming.

        Returns:
            None.
        """

        def bind(seq, fn):
            """Create a global application shortcut for the given key sequence.

            Args:
                seq: Key sequence string (e.g. "Alt+=").
                fn: Callable to invoke when the shortcut fires.

            Returns:
                The created QShortcut instance.
            """
            sc = QShortcut(QKeySequence(seq), self, activated=fn)
            sc.setContext(Qt.ApplicationShortcut)  # Global shortcut (focus-independent)
            return sc

        # Zoom in: Alt + / Alt =
        bind("Alt+=", self.zoom_in)  # Many keyboards produce "+" via Shift+=
        bind("Alt++", self.zoom_in)  # Some systems report it directly
        bind("Alt+Plus", self.zoom_in)  # Qt fallback name

        # Zoom out: Alt -
        bind("Alt+-", self.zoom_out)
        bind("Alt+Minus", self.zoom_out)  # Common Qt name
        bind("Alt+_", self.zoom_out)  # Some keyboards report Alt+Shift+-

    def _effective_max_time(self) -> float:
        """Return the maximum timeline bound used for rendering and seeking.

        Playback mode honors the archived duration closely so dragging and
        scrubbing stay aligned with recorded time. Live mode keeps at least a
        short forward-looking window so the timeline remains readable even when
        few events have been recorded.

        Returns:
            The effective maximum time bound in seconds.
        """
        if self.playback_mode:
            return max(self.total_duration, self.current_time, self.min_time)
        return max(self.total_duration, self.current_time, self.min_time + 60.0)

    def set_current_time(self, time_seconds: float):
        """Update the current cursor time and refresh the displayed stage state.

        Args:
            time_seconds: New current time in seconds.

        Returns:
            None.
        """
        self.current_time = float(time_seconds)
        if self.playback_mode and not self.timeline_bar.is_dragging:
            self.timeline_bar._calculate_visible_range()
        self._update_event_displays()
        self.timeline_bar.update()

    def set_total_duration(self, duration_seconds: float):
        """Set the total timeline duration.

        In playback mode this also recomputes the visible range so the timeline
        matches the archived run length.

        Args:
            duration_seconds: Total duration in seconds.

        Returns:
            None.
        """
        self.total_duration = max(0.0, float(duration_seconds))
        if self.playback_mode:
            self.timeline_bar._calculate_visible_range()
        self.timeline_bar.update()

    def add_event(self, time_seconds: float, label: str):
        """Add a labeled timeline event and keep the event list time-sorted.

        Args:
            time_seconds: Event timestamp in seconds.
            label: Event label to render on the timeline and emit through the
                stage-change summary.

        Returns:
            None.
        """
        self.events.append((time_seconds, label))
        self.events.sort(key=lambda x: x[0])

        if time_seconds < self.min_time:
            self.min_time = time_seconds

        self._update_event_displays()
        self.timeline_bar.update()

    def clear_events(self):
        """Remove all timeline events and reset the minimum time anchor.

        Returns:
            None.
        """
        self.events.clear()
        self.min_time = 0.0
        self._update_event_displays()
        self.timeline_bar.update()

    def zoom_in(self):
        """Increase the timeline zoom level and recompute the visible range.

        Returns:
            None.
        """
        self.zoom_level = min(self.zoom_level * 1.5, 10.0)
        self.timeline_bar._calculate_visible_range()
        self.timeline_bar.update()

    def zoom_out(self):
        """Decrease the timeline zoom level and recompute the visible range.

        Returns:
            None.
        """
        self.zoom_level = max(self.zoom_level / 1.5, 1.0)
        self.timeline_bar._calculate_visible_range()
        self.timeline_bar.update()

    def _update_event_displays(self):
        """Derive previous, current, and next event labels for the current time.

        When the derived stage tuple changes, the method emits
        ``stage_changed`` with the previous, current, and next event labels.

        Returns:
            None.
        """
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
    """Render the timeline axis and handle drag-based seeking.

    The bar paints time markers, event markers, the current-time cursor, and an
    always-readable dark background. During drag seeking it maintains a visible
    time window and can auto-scroll when the pointer reaches the left or right
    edge of the widget.
    """

    def __init__(self, timeline_view, parent=None):
        """Initialize the timeline bar for a parent ``TimelineView``.

        Args:
            timeline_view: Owning timeline view that provides timing state and
                receives emitted seek requests.
            parent: Optional parent widget.
        """
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
        """Paint the timeline background, markers, events, and current cursor.

        Args:
            _event: Qt paint event supplied by the widget system.

        Returns:
            None.
        """
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
        num_markers = (
            int((visible_start + visible_duration - start_marker) / marker_interval) + 2
        )

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

        # Keep the T+0 marker visible in playback too so the script axis stays familiar.
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
        if (
            visible_start
            <= self.timeline.current_time
            <= visible_start + visible_duration
        ):
            x = int(
                ((self.timeline.current_time - visible_start) / visible_duration)
                * width
            )
            painter.setPen(QPen(QColor("#00FF00"), 3))
            painter.drawLine(x, 0, x, height)

        painter.end()

    def mousePressEvent(self, event):
        """Start drag seeking on left-click and seek immediately to the pointer.

        Args:
            event: Qt mouse press event.

        Returns:
            None.
        """
        if event.button() == Qt.LeftButton:
            self.is_dragging = True
            if self.drag_visible_duration == 0.0:
                self._calculate_visible_range()
            self._seek_to_position(event.x())

    def mouseMoveEvent(self, event):
        """Update drag seeking and edge-triggered auto-scroll while dragging.

        Args:
            event: Qt mouse move event.

        Returns:
            None.
        """
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
        """Stop drag seeking and any active auto-scroll timer on left release.

        Args:
            event: Qt mouse release event.

        Returns:
            None.
        """
        if event.button() == Qt.LeftButton:
            self.is_dragging = False
            self.scroll_timer.stop()
            self.scroll_speed = 0.0
            self.last_seek_time = None

    def _auto_scroll(self):
        """Shift the visible window while drag seeking near the widget edges.

        The method updates the visible start time, clamps it to the effective
        timeline bounds, derives the seek time from the current cursor
        position, and emits ``seek_requested`` through the owning timeline.

        Returns:
            None.
        """
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
        new_time = self.drag_visible_start + (
            position_ratio * self.drag_visible_duration
        )
        new_time = max(min_time, min(new_time, max_time))

        self.timeline.seek_requested.emit(new_time)
        self.update()

    def _calculate_visible_range(self):
        """Recompute the visible time window from zoom level and current time.

        Returns:
            None.
        """
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
        """Convert an x position into a clamped seek time and emit it.

        Repeated emissions for nearly identical seek times are suppressed using
        a small threshold.

        Args:
            x_pos: Horizontal widget position in pixels.

        Returns:
            None.
        """
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
        """Choose a marker spacing based on the current visible duration.

        Args:
            visible_duration: Width of the current visible time window in
                seconds.

        Returns:
            Marker interval in seconds.
        """
        if visible_duration <= 60:
            return 10
        if visible_duration <= 300:
            return 30
        if visible_duration <= 600:
            return 60
        return 300
