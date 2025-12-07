from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                              QPushButton, QSlider, QFrame)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QFont, QPen
import logging

log = logging.getLogger("timeline")


class TimelineView(QWidget):
    """
    Timeline widget showing T+ time and script events
    Supports both live and playback modes
    """

    # Signal emitted when user seeks to a specific time (playback mode only)
    seek_requested = pyqtSignal(float)  # time in seconds

    def __init__(self, playback_mode=False, parent=None):
        super().__init__(parent)
        self.playback_mode = playback_mode
        self.current_time = 0.0  # Current T time in seconds (can be negative)
        self.total_duration = 0.0  # Total test duration in seconds (for playback)
        self.min_time = 0.0  # Minimum time (can be negative for pre-test events)
        self.zoom_level = 1.0  # Zoom level (1.0 = normal, 2.0 = 2x zoom, etc.)
        self.events = []  # List of timeline events [(time, label), ...]

        self._setup_ui()

    def _setup_ui(self):
        """Setup the timeline UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Timeline container with border
        timeline_container = QFrame()
        timeline_container.setStyleSheet("""
            QFrame {
                background-color: #2a2d2f;
                border: 1px solid #4CAF50;
            }
        """)
        container_layout = QVBoxLayout(timeline_container)
        container_layout.setContentsMargins(5, 5, 5, 5)
        container_layout.setSpacing(5)

        # Top bar with event display and controls
        top_bar = QHBoxLayout()
        top_bar.setAlignment(Qt.AlignCenter)

        # Event display section (3 columns: Prev | Current | Next)
        events_layout = QHBoxLayout()
        events_layout.setSpacing(20)

        # Previous Event column
        prev_col = QVBoxLayout()
        prev_col.setSpacing(2)  # Reduce gap between rows
        prev_label = QLabel("Prev")
        prev_label.setFont(QFont("Arial", 11, QFont.Bold))
        prev_label.setStyleSheet("color: #888888; border: none;")
        prev_label.setAlignment(Qt.AlignCenter)
        prev_col.addWidget(prev_label)

        self.prev_event_label = QLabel("")
        self.prev_event_label.setFont(QFont("Arial", 11))
        self.prev_event_label.setStyleSheet("color: #FFA726; border: none;")
        self.prev_event_label.setAlignment(Qt.AlignCenter)
        self.prev_event_label.setMinimumWidth(150)
        prev_col.addWidget(self.prev_event_label)
        events_layout.addLayout(prev_col)

        # Current Event column
        current_col = QVBoxLayout()
        current_col.setSpacing(2)  # Reduce gap between rows
        current_label = QLabel("Current")
        current_label.setFont(QFont("Arial", 11, QFont.Bold))
        current_label.setStyleSheet("color: #00FF00; border: none;")
        current_label.setAlignment(Qt.AlignCenter)
        current_col.addWidget(current_label)

        self.current_event_label = QLabel("")
        self.current_event_label.setFont(QFont("Arial", 11, QFont.Bold))
        self.current_event_label.setStyleSheet("color: #00FF00; border: none;")
        self.current_event_label.setAlignment(Qt.AlignCenter)
        self.current_event_label.setMinimumWidth(150)
        current_col.addWidget(self.current_event_label)
        events_layout.addLayout(current_col)

        # Next Event column
        next_col = QVBoxLayout()
        next_col.setSpacing(2)  # Reduce gap between rows
        next_label = QLabel("Next")
        next_label.setFont(QFont("Arial", 11, QFont.Bold))
        next_label.setStyleSheet("color: #888888; border: none;")
        next_label.setAlignment(Qt.AlignCenter)
        next_col.addWidget(next_label)

        self.next_event_label = QLabel("")
        self.next_event_label.setFont(QFont("Arial", 11))
        self.next_event_label.setStyleSheet("color: #FFA726; border: none;")
        self.next_event_label.setAlignment(Qt.AlignCenter)
        self.next_event_label.setMinimumWidth(150)
        next_col.addWidget(self.next_event_label)
        events_layout.addLayout(next_col)

        # Add event display
        top_bar.addLayout(events_layout)
        top_bar.addStretch()

        # Zoom controls (only in playback mode) - positioned on the right
        if self.playback_mode:
            zoom_label = QLabel("Zoom:")
            zoom_label.setStyleSheet("color: #aaaaaa; border: none;")
            top_bar.addWidget(zoom_label)

            zoom_out_btn = QPushButton("-")
            zoom_out_btn.setFixedSize(30, 25)
            zoom_out_btn.clicked.connect(self.zoom_out)
            zoom_out_btn.setStyleSheet("""
                QPushButton {
                    background-color: #555555;
                    color: white;
                    border: 1px solid #777777;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #666666;
                }
            """)
            top_bar.addWidget(zoom_out_btn)

            self.zoom_display = QLabel("100%")
            self.zoom_display.setFixedWidth(50)
            self.zoom_display.setAlignment(Qt.AlignCenter)
            self.zoom_display.setStyleSheet("color: #ffffff; border: none;")
            top_bar.addWidget(self.zoom_display)

            zoom_in_btn = QPushButton("+")
            zoom_in_btn.setFixedSize(30, 25)
            zoom_in_btn.clicked.connect(self.zoom_in)
            zoom_in_btn.setStyleSheet("""
                QPushButton {
                    background-color: #555555;
                    color: white;
                    border: 1px solid #777777;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #666666;
                }
            """)
            top_bar.addWidget(zoom_in_btn)

        container_layout.addLayout(top_bar)

        # Timeline bar (custom painted widget)
        self.timeline_bar = TimelineBar(self)
        self.timeline_bar.setMinimumHeight(60)
        self.timeline_bar.setStyleSheet("background-color: #1e1e1e; border: 1px solid #555555;")
        container_layout.addWidget(self.timeline_bar)

        # Playback controls (only in playback mode)
        if self.playback_mode:
            controls_layout = QHBoxLayout()

            # Seek slider
            self.seek_slider = QSlider(Qt.Horizontal)
            self.seek_slider.setMinimum(0)
            self.seek_slider.setMaximum(1000)  # Will be scaled to actual duration
            self.seek_slider.valueChanged.connect(self._on_seek_slider_changed)
            controls_layout.addWidget(self.seek_slider)

            # Duration label
            self.duration_label = QLabel("/ 00:00:00")
            self.duration_label.setFont(QFont("Courier New", 9))
            self.duration_label.setStyleSheet("color: #aaaaaa; border: none;")
            controls_layout.addWidget(self.duration_label)

            container_layout.addLayout(controls_layout)

        layout.addWidget(timeline_container)

    def set_current_time(self, time_seconds):
        """Update current time in seconds (can be negative)"""
        self.current_time = time_seconds
        self._update_event_displays()
        self.timeline_bar.update()

        # Update seek slider position (without triggering signal)
        if self.playback_mode:
            time_range = self.total_duration - self.min_time
            if time_range > 0:
                self.seek_slider.blockSignals(True)
                # Map current time to slider range (0-1000)
                normalized_time = (time_seconds - self.min_time) / time_range
                slider_pos = int(normalized_time * 1000)
                self.seek_slider.setValue(max(0, min(1000, slider_pos)))
                self.seek_slider.blockSignals(False)

    def set_total_duration(self, duration_seconds):
        """Set total duration (for playback mode)"""
        self.total_duration = duration_seconds
        if self.playback_mode:
            hours = int(duration_seconds // 3600)
            minutes = int((duration_seconds % 3600) // 60)
            seconds = int(duration_seconds % 60)
            self.duration_label.setText(f"/ {hours:02d}:{minutes:02d}:{seconds:02d}")
        self.timeline_bar.update()

    def add_event(self, time_seconds, label):
        """Add an event marker to the timeline"""
        self.events.append((time_seconds, label))
        self.events.sort(key=lambda x: x[0])  # Sort by time

        # Update minimum time if this event is earlier
        if time_seconds < self.min_time:
            self.min_time = time_seconds

        self.timeline_bar.update()
        sign = "+" if time_seconds >= 0 else ""
        log.debug(f"Added timeline event: {label} at T{sign}{time_seconds}s")

    def clear_events(self):
        """Clear all timeline events"""
        self.events.clear()
        self.min_time = 0.0
        self.timeline_bar.update()

    def zoom_in(self):
        """Zoom in on timeline"""
        self.zoom_level = min(self.zoom_level * 1.5, 10.0)  # Max 10x zoom
        self._update_zoom_display()
        # Recalculate visible range for new zoom level
        self.timeline_bar._calculate_visible_range()
        self.timeline_bar.update()
        log.debug(f"Timeline zoom in: {self.zoom_level:.1f}x")

    def zoom_out(self):
        """Zoom out on timeline"""
        self.zoom_level = max(self.zoom_level / 1.5, 1.0)  # Min 1.0x zoom (100% = full range)
        self._update_zoom_display()
        # Recalculate visible range for new zoom level
        self.timeline_bar._calculate_visible_range()
        self.timeline_bar.update()
        log.debug(f"Timeline zoom out: {self.zoom_level:.1f}x")

    def _update_zoom_display(self):
        """Update zoom percentage display"""
        if self.playback_mode:
            self.zoom_display.setText(f"{int(self.zoom_level * 100)}%")

    def _update_event_displays(self):
        """Update prev/current/next event labels based on current time"""
        if not self.events:
            self.prev_event_label.setText("")
            self.current_event_label.setText("")
            self.next_event_label.setText("")
            return

        # Find events relative to current time (Current = most recent passed, Prev = before current, Next = upcoming)

        current_event_idx = None

        # Find the most recent event that has passed (or is happening now)
        for idx, (event_time, _) in enumerate(self.events):
            if event_time <= self.current_time:
                current_event_idx = idx
            else:
                break

        # Extract prev, current, and next based on index
        prev_event = None
        current_event = None
        next_event = None

        if current_event_idx is not None:
            # We have a current event (most recent passed event)
            current_event = self.events[current_event_idx]

            # Previous is the event before current
            if current_event_idx > 0:
                prev_event = self.events[current_event_idx - 1]

            # Next is the event after current
            if current_event_idx + 1 < len(self.events):
                next_event = self.events[current_event_idx + 1]
        else:
            # We're before the first event
            if len(self.events) > 0:
                next_event = self.events[0]

        # Update labels
        if prev_event:
            self.prev_event_label.setText(prev_event[1])
        else:
            self.prev_event_label.setText("")

        if current_event:
            self.current_event_label.setText(current_event[1])
        else:
            self.current_event_label.setText("")

        if next_event:
            self.next_event_label.setText(next_event[1])
        else:
            self.next_event_label.setText("")

    def _on_seek_slider_changed(self, value):
        """Handle seek slider change"""
        if self.playback_mode:
            # Map slider value (0-1000) to full time range (min_time to total_duration)
            time_range = self.total_duration - self.min_time
            if time_range > 0:
                seek_time = self.min_time + (value / 1000.0) * time_range
                self.seek_requested.emit(seek_time)
                sign = "+" if seek_time >= 0 else ""
                log.debug(f"Seek requested to: T{sign}{seek_time:.2f}s")


class TimelineBar(QWidget):
    """Custom widget for drawing the timeline bar"""

    def __init__(self, timeline_view, parent=None):
        super().__init__(parent)
        self.timeline = timeline_view
        self.setMouseTracking(True)  # Enable mouse tracking
        self.setCursor(Qt.PointingHandCursor)  # Show hand cursor to indicate clickable
        self.is_dragging = False  # Track if user is dragging
        self.drag_visible_start = 0.0  # Store visible start when drag begins
        self.drag_visible_duration = 0.0  # Store visible duration when drag begins
        self.last_seek_time = None  # Track last seeked time to prevent redundant seeks

        # Auto-scroll at edges
        self.scroll_timer = QTimer(self)
        self.scroll_timer.timeout.connect(self._auto_scroll)
        self.scroll_speed = 0.0  # Pixels per timer tick
        self.edge_threshold = 30  # Pixels from edge to trigger auto-scroll

    def paintEvent(self, _event):
        """Custom paint event to draw timeline"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()

        # Draw background
        painter.fillRect(0, 0, width, height, QColor("#1e1e1e"))

        # Use stored visible range (updated during dragging/scrolling, no auto-recenter)
        visible_start = self.drag_visible_start
        visible_duration = self.drag_visible_duration

        # If not initialized, calculate initial range
        if visible_duration == 0.0:
            time_range = self.timeline.total_duration - self.timeline.min_time
            if time_range <= 0:
                time_range = max(60, abs(self.timeline.min_time) + 60)

            visible_duration = time_range / self.timeline.zoom_level
            visible_start = self.timeline.current_time - (visible_duration / 2)

            if visible_start < self.timeline.min_time:
                visible_start = self.timeline.min_time
            elif visible_start + visible_duration > self.timeline.total_duration:
                visible_start = self.timeline.total_duration - visible_duration

            if visible_duration >= time_range:
                visible_start = self.timeline.min_time
                visible_duration = time_range

            self.drag_visible_start = visible_start
            self.drag_visible_duration = visible_duration

        # Draw time markers
        marker_interval = self._calculate_marker_interval(visible_duration)
        start_marker = int(visible_start / marker_interval) * marker_interval
        num_markers = int((visible_start + visible_duration - start_marker) / marker_interval) + 2

        painter.setPen(QPen(QColor("#555555"), 1))
        painter.setFont(QFont("Arial", 8))

        for i in range(num_markers):
            time_pos = start_marker + i * marker_interval
            if visible_start <= time_pos <= visible_start + visible_duration:
                # Calculate x position
                x = int(((time_pos - visible_start) / visible_duration) * width)

                # Draw marker line
                painter.drawLine(x, height - 15, x, height - 5)

                # Draw time label with T+/T- notation
                abs_time = abs(time_pos)
                minutes = int(abs_time // 60)
                seconds = int(abs_time % 60)
                sign = "+" if time_pos >= 0 else "-"
                label = f"T{sign}{minutes}:{seconds:02d}"
                painter.setPen(QColor("#888888"))
                painter.drawText(x - 20, height - 18, label)
                painter.setPen(QColor("#555555"))

        # Draw T+0 marker (special line)
        if visible_start <= 0 <= visible_start + visible_duration:
            x = int((0 - visible_start) / visible_duration * width)
            painter.setPen(QPen(QColor("#FFFFFF"), 2))  # White line for T+0
            painter.drawLine(x, height - 20, x, height - 5)
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(QFont("Arial", 8, QFont.Bold))
            painter.drawText(x - 15, height - 22, "T+0")

        # Draw events
        for event_time, event_label in self.timeline.events:
            if visible_start <= event_time <= visible_start + visible_duration:
                x = int(((event_time - visible_start) / visible_duration) * width)

                # Draw event marker (vertical line)
                painter.setPen(QPen(QColor("#FFA726"), 2))  # Orange
                painter.drawLine(x, 5, x, height - 20)

                # Draw event label
                painter.setPen(QColor("#FFA726"))
                painter.setFont(QFont("Arial", 8, QFont.Bold))
                painter.drawText(x + 3, 15, event_label)

        # Draw current time indicator
        if visible_start <= self.timeline.current_time <= visible_start + visible_duration:
            x = int(((self.timeline.current_time - visible_start) / visible_duration) * width)
            painter.setPen(QPen(QColor("#00FF00"), 3))  # Green
            painter.drawLine(x, 0, x, height)

        painter.end()

    def mousePressEvent(self, event):
        """Handle mouse press - start dragging"""
        if event.button() == Qt.LeftButton:
            self.is_dragging = True
            # Initialize visible range if needed
            if self.drag_visible_duration == 0.0:
                self._calculate_visible_range()
            # Seek to clicked position (using existing visible range)
            self._seek_to_position(event.x())

    def mouseMoveEvent(self, event):
        """Handle mouse move - continue dragging"""
        if self.is_dragging:
            x_pos = event.x()
            width = self.width()

            # Check if near edges for auto-scroll
            if x_pos < self.edge_threshold:
                # Near left edge - scroll left
                distance_from_edge = self.edge_threshold - x_pos
                self.scroll_speed = -distance_from_edge / 10.0  # Negative = scroll left
                if not self.scroll_timer.isActive():
                    self.scroll_timer.start(50)  # Update every 50ms
            elif x_pos > width - self.edge_threshold:
                # Near right edge - scroll right
                distance_from_edge = x_pos - (width - self.edge_threshold)
                self.scroll_speed = distance_from_edge / 10.0  # Positive = scroll right
                if not self.scroll_timer.isActive():
                    self.scroll_timer.start(50)
            else:
                # Not near edge - stop auto-scroll
                self.scroll_timer.stop()
                self.scroll_speed = 0.0

            self._seek_to_position(x_pos)

    def mouseReleaseEvent(self, event):
        """Handle mouse release - end dragging"""
        if event.button() == Qt.LeftButton:
            self.is_dragging = False
            self.scroll_timer.stop()
            self.scroll_speed = 0.0
            self.last_seek_time = None  # Reset for next drag

    def _auto_scroll(self):
        """Auto-scroll the timeline when dragging near edges"""
        if not self.is_dragging or self.scroll_speed == 0.0:
            return

        # Calculate time shift from scroll speed (pixels per tick converted to time units)
        time_per_pixel = self.drag_visible_duration / self.width()
        time_shift = self.scroll_speed * time_per_pixel

        # Shift the visible range
        new_visible_start = self.drag_visible_start + time_shift

        # Clamp to valid range
        if new_visible_start < self.timeline.min_time:
            new_visible_start = self.timeline.min_time
            self.scroll_timer.stop()  # Stop at boundary
        elif new_visible_start + self.drag_visible_duration > self.timeline.total_duration:
            new_visible_start = self.timeline.total_duration - self.drag_visible_duration
            self.scroll_timer.stop()  # Stop at boundary

        # Update stored range
        self.drag_visible_start = new_visible_start

        # Update current time to follow scroll (keep indicator at same relative position)
        width = self.width()
        last_mouse_x = self.mapFromGlobal(self.cursor().pos()).x()
        position_ratio = max(0, min(1, last_mouse_x / width))
        new_time = self.drag_visible_start + (position_ratio * self.drag_visible_duration)
        new_time = max(self.timeline.min_time, min(new_time, self.timeline.total_duration))

        # Emit seek to update timeline
        self.timeline.seek_requested.emit(new_time)
        self.update()  # Trigger repaint

    def _calculate_visible_range(self):
        """Calculate and store the visible time range (for dragging)"""
        # Calculate the full time range
        time_range = self.timeline.total_duration - self.timeline.min_time
        if time_range <= 0:
            time_range = max(60, abs(self.timeline.min_time) + 60)

        # Apply zoom to visible duration
        visible_duration = time_range / self.timeline.zoom_level

        # Center view around current time
        visible_start = self.timeline.current_time - (visible_duration / 2)

        # Clamp to valid range
        if visible_start < self.timeline.min_time:
            visible_start = self.timeline.min_time
        elif visible_start + visible_duration > self.timeline.total_duration:
            visible_start = self.timeline.total_duration - visible_duration

        # If zoomed out beyond full range, show full range
        if visible_duration >= time_range:
            visible_start = self.timeline.min_time
            visible_duration = time_range

        # Store for use during dragging
        self.drag_visible_start = visible_start
        self.drag_visible_duration = visible_duration

    def _seek_to_position(self, x_pos):
        """Calculate and seek to time based on x position"""
        width = self.width()

        # Clamp x position to valid range
        x_pos = max(0, min(x_pos, width))

        # Use stored visible range (calculated when drag started)
        visible_start = self.drag_visible_start
        visible_duration = self.drag_visible_duration

        # Convert position to time based on displayed timeline
        position_ratio = x_pos / width
        seek_time = visible_start + (position_ratio * visible_duration)

        # Clamp to valid time range
        seek_time = max(self.timeline.min_time, min(seek_time, self.timeline.total_duration))

        # Only emit seek signal if time has changed (prevents redundant seeks)
        if self.last_seek_time is None or abs(seek_time - self.last_seek_time) > 0.001:
            self.last_seek_time = seek_time
            self.timeline.seek_requested.emit(seek_time)

    def _calculate_marker_interval(self, visible_duration):
        """Calculate appropriate time marker interval"""
        if visible_duration <= 60:
            return 10  # 10 second intervals
        elif visible_duration <= 300:
            return 30  # 30 second intervals
        elif visible_duration <= 600:
            return 60  # 1 minute intervals
        else:
            return 300  # 5 minute intervals
