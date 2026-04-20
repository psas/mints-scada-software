"""gui/view_graph.py

Matplotlib-backed graph widget for live and playback sensor history.

The widget renders one line per registered device, pulls history either from
the device object itself or from an attached graph data provider, and keeps the
visible window aligned to the current live or playback time range.
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout
import matplotlib
import matplotlib.lines
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg  # type: ignore
from matplotlib.figure import Figure
from PyQt5.QtCore import QTimer, pyqtSignal
import time
import numpy as np
from nexus import GenericSensor
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .graph_provider import BaseGraphDataProvider

log = logging.getLogger("Graph")


class GraphView(QWidget):
    """Display time-series sensor data for live and playback modes.

    The widget tracks a set of registered sensor-like objects, renders one
    matplotlib line per device, and refreshes on a timer. History can come
    directly from each sensor's ``history`` attribute or from an attached graph
    provider that serves samples for the current graph window.
    """

    durationChanged = pyqtSignal(int)
    seriesChanged = pyqtSignal()

    FOREGROUND_COLOR = "#f4f4f4"
    BACKGROUND_COLOR = "#19232d"
    LEGEND_COLOR = "#353535"

    def __init__(self):
        """Initialize the graph widget, matplotlib canvas, and refresh timer."""
        super().__init__()
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.setLayout(self.layout)

        self.duration = 60
        self.sensors: list[object] = []
        self.lines: list[matplotlib.lines.Line2D] = []
        self._enabled_channels: dict[str, bool] = {}
        self._graph_provider = None

        logging.getLogger("matplotlib").setLevel(logging.INFO)

        self.fig = Figure(figsize=(5, 4), dpi=100)
        self.axes = self.fig.add_subplot(111)
        self.canvas = FigureCanvasQTAgg(self.fig)

        self.fig.set_facecolor(self.BACKGROUND_COLOR)
        self.axes.set_facecolor(self.BACKGROUND_COLOR)
        self.axes.spines["bottom"].set_color(self.FOREGROUND_COLOR)
        self.axes.spines["top"].set_color(self.FOREGROUND_COLOR)
        self.axes.spines["right"].set_color(self.FOREGROUND_COLOR)
        self.axes.spines["left"].set_color(self.FOREGROUND_COLOR)
        self.axes.tick_params(axis="x", colors=self.FOREGROUND_COLOR)
        self.axes.tick_params(axis="y", colors=self.FOREGROUND_COLOR)
        self.axes.yaxis.label.set_color(self.FOREGROUND_COLOR)
        self.axes.xaxis.label.set_color(self.FOREGROUND_COLOR)
        self.axes.title.set_color(self.FOREGROUND_COLOR)
        self.axes.grid("both", "major")

        self.fig.tight_layout(pad=2)
        self.axes.set_xlim(0, 100)
        self.axes.set_ylim(0, 2)

        self.layout.addWidget(self.canvas, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._update)
        self.timer.start()

    def attach_graph_provider(self, provider: "BaseGraphDataProvider | None") -> None:
        """Attach the current graph data provider and refresh the plot.

        Args:
            provider: Provider used to supply graph samples when device-local
                history is unavailable. Pass None to clear the provider.

        Returns:
            None.
        """
        self._graph_provider = provider
        self._update()

    def detach_graph_provider(self) -> None:
        """Detach the current graph data provider and refresh the plot.

        Returns:
            None.
        """
        self._graph_provider = None
        self._update()

    def _display_label(self, sensor: object) -> str:
        """Return the legend label for a sensor-like object.

        Args:
            sensor: Sensor-like object with optional ``display_name`` and
                ``device_id`` attributes.

        Returns:
            The display name when present, otherwise the runtime device ID, or
            ``"Unknown"`` when neither attribute exists.
        """
        return getattr(sensor, "display_name", getattr(sensor, "device_id", "Unknown"))

    def _runtime_id(self, sensor: object) -> str:
        """Return the runtime device identifier for a sensor-like object.

        Args:
            sensor: Sensor-like object with an optional ``device_id`` attribute.

        Returns:
            The device ID string, or an empty string when the object does not
            expose one.
        """
        return getattr(sensor, "device_id", "")

    def _extract_history(self, sensor: object):
        """Return timestamp/value history for a sensor.

        The method first tries to read a two-row history array from the sensor
        object itself. If that is unavailable, it queries the attached graph
        provider for samples in the current live or playback window and converts
        them into the same two-row numpy shape.

        Args:
            sensor: Sensor-like object to read history from.

        Returns:
            A two-row numpy array where row 0 contains timestamps and row 1
            contains values, or None when no usable history is available.
        """
        hist = getattr(sensor, "history", None)
        if hist is not None:
            try:
                hist = np.asarray(hist)
            except Exception:
                log.exception(
                    "Failed to convert history for sensor %s", self._runtime_id(sensor)
                )
                hist = None
            else:
                if hist.ndim == 2 and hist.shape[0] >= 2:
                    return hist

        runtime_id = self._runtime_id(sensor)
        if not runtime_id or self._graph_provider is None:
            return None

        try:
            provider_window = getattr(self._graph_provider, "window", None)
            if provider_window is not None and provider_window.end_ts is not None:
                end_ts = float(provider_window.end_ts)
                start_ts = (
                    float(provider_window.start_ts)
                    if provider_window.start_ts is not None
                    else end_ts - float(self.duration)
                )
            else:
                end_ts = time.time()
                start_ts = end_ts - float(self.duration)
            samples = self._graph_provider.get_samples(
                channel_keys=[runtime_id],
                start_ts=start_ts,
                end_ts=end_ts,
            )
        except Exception:
            log.exception("Failed to query provider history for sensor %s", runtime_id)
            return None

        if not samples:
            return None

        try:
            xs = np.asarray([sample.timestamp for sample in samples], dtype=float)
            ys = np.asarray([sample.value for sample in samples], dtype=float)
            if xs.size == 0 or ys.size == 0:
                return None
            return np.vstack((xs, ys))
        except Exception:
            log.exception("Failed to build provider history for sensor %s", runtime_id)
            return None

    def _is_enabled(self, sensor: object) -> bool:
        """Return whether a sensor's channel is currently enabled.

        Args:
            sensor: Sensor-like object to inspect.

        Returns:
            True when the channel is enabled or has not been explicitly
            disabled.
        """
        runtime_id = self._runtime_id(sensor)
        return self._enabled_channels.get(runtime_id, True)

    def _set_empty_line(self, idx: int):
        """Clear the plotted data for a line slot.

        Args:
            idx: Index of the line to clear.

        Returns:
            None.
        """
        if 0 <= idx < len(self.lines):
            self.lines[idx].set_xdata([None])
            self.lines[idx].set_ydata([None])

    def _update(self):
        """Refresh all plotted series for the current graph window.

        The update uses the provider's explicit playback window when available.
        Otherwise it uses the current wall-clock time and the configured graph
        duration. Disabled channels and channels without usable history are
        cleared from the plot.

        Returns:
            None.
        """
        ymin = 0.0
        ymax = 0.0
        visible_count = 0

        provider_window = getattr(self._graph_provider, "window", None)
        if provider_window is not None and provider_window.end_ts is not None:
            start = float(provider_window.end_ts)
            thresh = (
                float(provider_window.start_ts)
                if provider_window.start_ts is not None
                else start - self.duration
            )
        else:
            start = time.time()
            thresh = start - self.duration

        for idx, sensor in enumerate(self.sensors):
            try:
                if idx >= len(self.lines):
                    continue

                if not self._is_enabled(sensor):
                    self._set_empty_line(idx)
                    continue

                hist = self._extract_history(sensor)
                if hist is None:
                    self._set_empty_line(idx)
                    continue

                vals = hist[:, hist[0] > thresh]
                if vals.shape[1] == 0:
                    self._set_empty_line(idx)
                    continue

                x = vals[0] - start
                y = vals[1]
                if len(y) == 0:
                    self._set_empty_line(idx)
                    continue

                self.lines[idx].set_xdata(x)
                self.lines[idx].set_ydata(y)
                ymin = min(float(np.min(y)), ymin)
                ymax = max(float(np.max(y)), ymax)
                visible_count += 1

            except Exception:
                log.exception(
                    "Graph update failed for sensor %s",
                    self._runtime_id(sensor),
                )
                self._set_empty_line(idx)

        if visible_count == 0:
            self.axes.set_ylim(-0.1, 0.1)
        else:
            self.axes.set_ylim(ymin - 0.1, ymax + 0.1)
        self.axes.set_xlim(-self.duration, 0)
        self.canvas.draw_idle()

    def is_channel_enabled(self, channel: str) -> bool:
        """Return whether a channel is enabled for plotting.

        Args:
            channel: Runtime device ID for the channel.

        Returns:
            True when the channel is enabled or has not been explicitly
            disabled.
        """
        return self._enabled_channels.get(channel, True)

    def legend_entries(self) -> list[tuple[str, str, str, bool]]:
        """Build the current legend metadata for all registered series.

        Returns:
            A list of tuples containing runtime ID, display label, matplotlib
            line color, and enabled state for each registered sensor.
        """
        entries = []
        for sensor, line in zip(self.sensors, self.lines):
            runtime_id = self._runtime_id(sensor)
            entries.append(
                (
                    runtime_id,
                    self._display_label(sensor),
                    line.get_color(),
                    self.is_channel_enabled(runtime_id),
                )
            )
        return entries

    def add_device(self, sensor: object, graphed: bool = True) -> bool:
        """Register a device as a plotted series.

        If a device with the same runtime ID already exists, the method updates
        its enabled state instead of creating a duplicate line.

        Args:
            sensor: Sensor-like object to add.
            graphed: Whether the channel should start enabled.

        Returns:
            True when a new series was added. False when the device already
            existed and only its enabled state was updated.
        """
        runtime_id = self._runtime_id(sensor)
        if runtime_id and any(
            self._runtime_id(existing) == runtime_id for existing in self.sensors
        ):
            self.enableChannel(runtime_id, graphed)
            return False

        self.sensors.append(sensor)
        label = self._display_label(sensor)
        line = self.axes.plot([None], [None], label=label)[0]
        self.lines.append(line)

        if runtime_id:
            self._enabled_channels[runtime_id] = bool(graphed)

        self.seriesChanged.emit()
        self._update()
        return True

    def addSensor(self, sensor: GenericSensor, graphed=True):
        """Add a sensor using the legacy script-facing API.

        Args:
            sensor: Sensor instance to add.
            graphed: Whether the channel should start enabled.

        Returns:
            The result from ``add_device``.
        """
        return self.add_device(sensor, graphed)

    def remove_device(self, channel: str) -> bool:
        """Remove a plotted series by runtime device ID.

        Args:
            channel: Runtime device ID to remove.

        Returns:
            True when a matching device was removed, or False when no matching
            series exists.
        """
        for idx, sensor in enumerate(self.sensors):
            if self._runtime_id(sensor) != channel:
                continue

            self.sensors.pop(idx)
            line = self.lines.pop(idx)
            try:
                line.remove()
            except Exception:
                pass
            self._enabled_channels.pop(channel, None)
            self.seriesChanged.emit()
            self._update()
            return True
        return False

    def clear_devices(self):
        """Remove all registered devices and plotted lines.

        Returns:
            None.
        """
        self.sensors.clear()
        while self.lines:
            line = self.lines.pop()
            try:
                line.remove()
            except Exception:
                pass
        self._enabled_channels.clear()
        self.seriesChanged.emit()
        self._update()

    def set_devices(self, devices: list[object], graphed: bool = True):
        """Replace the plotted device set.

        Args:
            devices: New sensor-like objects to register.
            graphed: Whether each channel should start enabled.

        Returns:
            None.
        """
        self.clear_devices()
        for device in devices:
            self.add_device(device, graphed)
        self.seriesChanged.emit()
        self._update()

    def set_duration(self, duration: int):
        """Set the visible graph duration in seconds.

        Args:
            duration: Requested time window length in seconds.

        Returns:
            None.
        """
        self.duration = max(1, int(duration))
        self.durationChanged.emit(int(self.duration))
        self._update()

    # Functions for use in scripts
    def setDuration(self, duration: int):
        """Set the visible graph duration through the legacy script API.

        Args:
            duration: Requested time window length in seconds.

        Returns:
            None.
        """
        self.set_duration(duration)

    def enableChannel(self, channel: str, state: bool = True) -> bool:
        """Enable or disable a plotted channel by runtime device ID.

        Args:
            channel: Runtime device ID of the channel.
            state: Whether the channel should be enabled.

        Returns:
            True when the channel exists and its enabled state was updated, or
            False when no matching channel is registered.
        """
        for sensor in self.sensors:
            if self._runtime_id(sensor) == channel:
                self._enabled_channels[channel] = bool(state)
                self.seriesChanged.emit()
                self._update()
                return True
        return False
