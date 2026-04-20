"""gui/scada_window.py

SCADA window for live control and playback visualization.

This module provides the right-screen SCADA window that renders the SVG-based
process diagram, mirrors valve state from backend snapshots and structured
events, and routes operator actions such as valve commands and abort requests
through backend- or relay-attached callbacks. In playback mode the same window
becomes a read-only state viewer driven by recorded history.
"""

from __future__ import annotations

from pathlib import Path
import logging
import re
from typing import Any

from PyQt5.QtCore import QUrl, Qt
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWebEngineWidgets import QWebEngineSettings, QWebEngineView
import qdarkstyle

from settings import get_controllable_valve_ids, LIVE_STARTUP_STATE
from gui.scada_bridge import ScadaBridge
from gui.scada_webpage import ScadaWebPage
from historymanager.paths import HISTORY_ROOT_DIRNAME

logger = logging.getLogger(__name__)


class ScadaWindow(QMainWindow):
    """Render the SCADA diagram and synchronize valve state with backend data.

    The window hosts the SVG-based SCADA view, tracks display state for
    controllable valves, and mirrors state changes from backend snapshots,
    structured events, and command results. In live mode it can emit valve and
    abort-related actions through callbacks attached by the surrounding GUI
    runtime. In playback mode it disables SCADA interactivity and applies
    recorded state as the playback position changes.
    """

    OPEN_COMMAND_NAMES = {"open", "open_valve", "valve_open"}
    CLOSE_COMMAND_NAMES = {"close", "close_valve", "valve_close"}

    def __init__(
        self, playback_mode: bool = False, test_name: str | None = None, manager=None
    ):
        """Initialize the SCADA window and its local runtime state.

        Args:
            playback_mode: Whether the window should run as a read-only playback
                viewer instead of a live control surface.
            test_name: Optional run or test name used for the playback window
                title.
            manager: Optional window manager object attached by the surrounding
                GUI runtime.
        """
        super().__init__()
        self.manager = manager
        self.playback_mode = bool(playback_mode)
        self.test_name = test_name

        self.backend_state_snapshot: dict[str, Any] = {}
        self.backend_run_status: dict[str, Any] = {}
        self.playback_load_summary: dict[str, Any] = {}
        self.playback_seek_summary: dict[str, Any] = {}
        self.playback_time: float = 0.0

        self._svg_loaded = False
        self.web_view: QWebEngineView | None = None
        self.bridge: ScadaBridge | None = None
        self.channel: QWebChannel | None = None

        self.xv_device_ids: tuple[str, ...] = get_controllable_valve_ids()
        self.xv_states = {device_id: "default" for device_id in self.xv_device_ids}
        if not self.playback_mode:
            for valve_id in self.xv_device_ids:
                self.xv_states[valve_id] = self._initial_valve_state(valve_id)
        self.pending_xv_commands: dict[str, str] = {}

        title_suffix = " - Playback" if self.playback_mode else " - Right Screen"
        self.setWindowTitle(f"minTS SCADA{title_suffix}")
        self.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyqt5"))

        self._build_ui()

    def _build_ui(self) -> None:
        """Build the SCADA layout, SVG view, and live-mode control buttons.

        The SVG diagram is loaded into a ``QWebEngineView`` with a
        ``QWebChannel`` bridge so SVG clicks can be forwarded into Python. In
        live mode a side button column provides abort and clear-abort actions.
        """
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        diagram = QFrame()
        diagram.setStyleSheet(
            "QFrame{background:#111; border:1px solid #444; border-radius:10px;}"
        )
        dlay = QVBoxLayout(diagram)
        dlay.setContentsMargins(12, 12, 12, 12)

        svg_path = (
            Path(__file__).resolve().parent.parent
            / "src/MinTS_SCADA_stable_v1_bridge_ready.svg"
        )
        if svg_path.exists():
            self.web_view = QWebEngineView()
            self.web_view.setPage(ScadaWebPage(self.web_view))
            self.web_view.setStyleSheet("background:#111; border:none;")
            self.web_view.settings().setAttribute(
                QWebEngineSettings.JavascriptEnabled, True
            )
            if self.playback_mode:
                self.web_view.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                self.web_view.setFocusPolicy(Qt.NoFocus)

            self.bridge = ScadaBridge(self)
            self.bridge.valve_clicked.connect(self.on_valve_clicked)
            self.channel = QWebChannel(self.web_view.page())
            self.channel.registerObject("bridge", self.bridge)
            self.web_view.page().setWebChannel(self.channel)

            svg_text = svg_path.read_text(encoding="utf-8")
            svg_text = re.sub(r"<\?xml[^>]*\?>", "", svg_text, flags=re.IGNORECASE)
            svg_text = re.sub(r"<!DOCTYPE[^>]*>", "", svg_text, flags=re.IGNORECASE)

            html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset=\"utf-8\">
<style>
html, body {{ margin: 0; padding: 0; background: #111; overflow: hidden; }}
svg {{ width: 100%; height: 100%; display: block; background: #111; }}
</style>
<script src=\"qrc:///qtwebchannel/qwebchannel.js\"></script>
<script>
// Initialize the Qt WebChannel bridge so SVG JS can call into Python.
// qt.webChannelTransport is provided by QWebEngineView when a QWebChannel
// is attached to the page.  The callback fires once the channel is ready
// and exposes the registered "bridge" object as window.bridge.
new QWebChannel(qt.webChannelTransport, function(channel) {{
    window.bridge = channel.objects.bridge;
}});
</script>
</head>
<body>
{svg_text}
</body>
</html>
"""
            base_url = QUrl.fromLocalFile(str(svg_path.parent) + "/")
            self.web_view.loadFinished.connect(self._on_svg_loaded)
            self.web_view.setHtml(html, base_url)
            dlay.addWidget(self.web_view)
            logger.info("[SCADA] Loaded SVG: %s", svg_path)
        else:
            error_label = QLabel(f"SVG file not found:\n{svg_path}")
            error_label.setStyleSheet("color:#bbb; font-size:16px;")
            dlay.addWidget(error_label)
            logger.error("[SCADA] SVG file not found: %s", svg_path)

        layout.addWidget(diagram, 1)

        if not self.playback_mode:
            btn_col = QFrame()
            btn_col.setFixedWidth(220)
            btn_col.setStyleSheet(
                "QFrame{background:#2b2b2b; border:1px solid #444; border-radius:10px;}"
            )
            blay = QVBoxLayout(btn_col)
            blay.setContentsMargins(16, 16, 16, 16)
            blay.setSpacing(14)

            self.btn_abort = QPushButton("Abort")
            self.btn_abort.setMinimumHeight(72)
            self.btn_abort.clicked.connect(self._on_abort_clicked)
            blay.addWidget(self.btn_abort)

            self.btn_clear_abort = QPushButton("Back to Normal")
            self.btn_clear_abort.setMinimumHeight(72)
            self.btn_clear_abort.clicked.connect(self._on_clear_abort_clicked)
            blay.addWidget(self.btn_clear_abort)

            for button in (self.btn_abort, self.btn_clear_abort):
                button.setStyleSheet(
                    """
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
                    """
                )

            blay.addStretch()
            layout.addWidget(btn_col, 0)

    def _on_svg_loaded(self, ok: bool) -> None:
        """Finalize SVG startup and replay any state that arrived before load.

        Args:
            ok: Whether the web view finished loading the SVG HTML successfully.
        """
        self._svg_loaded = bool(ok)
        if not ok:
            logger.error("[SCADA] SVG web view failed to load")
            return
        logger.info("[SCADA] SVG web view finished loading")
        if self.playback_mode:
            self._apply_playback_lock_to_svg()
        # Re-apply device states from any snapshot that arrived before the SVG
        # was ready (those pushes were silently dropped).
        if self.backend_state_snapshot:
            states = self._extract_device_states(self.backend_state_snapshot)
            if states:
                self._apply_device_states(states)
        self._sync_all_states_to_svg()
        if not self.playback_mode:
            request = getattr(self, "request_full_backend_state", None)
            if callable(request):
                try:
                    request()
                except Exception:
                    logger.debug("[SCADA] Could not request backend state on SVG load")

    def _apply_playback_lock_to_svg(self) -> None:
        """Disable clickable SVG controls for playback mode.

        The lock blocks pointer interaction on known valve control nodes and
        installs a capture-phase click handler so playback views cannot issue
        live control actions through the embedded SVG.
        """
        if self.web_view is None:
            return
        js = """
        (function() {
            var groups = document.querySelectorAll('.xv-control');
            var blockedIds = new Set();
            groups.forEach(function(group) {
                blockedIds.add(group.id);
                var nodes = [group].concat(Array.from(group.querySelectorAll('*')));
                nodes.forEach(function(node) {
                    try {
                        node.style.pointerEvents = 'none';
                        node.style.cursor = 'default';
                    } catch (e) {}
                });
            });
            document.querySelectorAll('.xv-state-label').forEach(function(label) {
                blockedIds.add(label.id);
                try {
                    label.style.pointerEvents = 'none';
                    label.style.cursor = 'default';
                } catch (e) {}
            });
            if (!window.__mintsPlaybackReadOnlyClickBlockerInstalled) {
                document.addEventListener('click', function(evt) {
                    var node = evt.target;
                    while (node) {
                        if (node.id && blockedIds.has(node.id)) {
                            evt.preventDefault();
                            evt.stopPropagation();
                            if (evt.stopImmediatePropagation) evt.stopImmediatePropagation();
                            return false;
                        }
                        node = node.parentElement;
                    }
                    return true;
                }, true);
                window.__mintsPlaybackReadOnlyClickBlockerInstalled = true;
            }
        })();
        """
        self.web_view.page().runJavaScript(js)

    def _normalize_state(self, state: Any) -> str:
        """Normalize backend, playback, or UI valve state values.

        Args:
            state: Raw state value from a snapshot, event, command result, or
                UI path.

        Returns:
            ``"open"``, ``"closed"``, or ``"default"``.
        """
        if isinstance(state, bool):
            return "open" if state else "closed"

        value = str(state or "default").strip().lower()
        if value in {"open", "opened", "on", "true", "1", "commanded_open"}:
            return "open"
        if value in {
            "closed",
            "close",
            "shut",
            "off",
            "false",
            "0",
            "commanded_closed",
        }:
            return "closed"
        return "default"

    def _initial_valve_state(self, valve_id: str) -> str:
        """Resolve the initial live-mode display state for a valve.

        The lookup prefers the current backend snapshot when one is already
        available. If no backend state exists yet, it falls back to
        ``LIVE_STARTUP_STATE`` and then to ``"default"``.

        Args:
            valve_id: Canonical valve device identifier.

        Returns:
            The normalized initial display state for the valve.
        """
        if self.backend_state_snapshot:
            states = self._extract_device_states(self.backend_state_snapshot)
            if valve_id in states:
                return self._normalize_state(states[valve_id])
        startup = LIVE_STARTUP_STATE.get(valve_id)
        if startup is not None:
            return self._normalize_state(startup)
        return "default"

    def _resolve_backend_device_id(self, valve_id: str) -> str | None:
        """Return the backend device identifier for a SCADA valve id.

        Args:
            valve_id: Valve identifier coming from the SCADA window or SVG.

        Returns:
            The matching backend device identifier when the valve is tracked by
            this window, otherwise None.
        """
        return valve_id if valve_id in self.xv_states else None

    def _resolve_svg_valve_id(self, device_id: str) -> str | None:
        """Return the SVG valve identifier for a backend device id.

        Args:
            device_id: Backend device identifier.

        Returns:
            The matching SVG valve identifier when the device is represented in
            this window, otherwise None.
        """
        return device_id if device_id in self.xv_states else None

    def _state_to_command_name(self, state: str) -> str | None:
        """Map a normalized display state to a backend valve command name.

        Args:
            state: Raw or normalized valve state.

        Returns:
            ``"open"`` for open states, ``"close"`` for closed states, or None
            when the state does not correspond to a commandable target state.
        """
        normalized = self._normalize_state(state)
        if normalized == "open":
            return "open"
        if normalized == "closed":
            return "close"
        return None

    def _command_name_to_state(self, command_name: Any) -> str | None:
        """Map a backend command name to the corresponding valve state.

        Args:
            command_name: Command name extracted from a structured event or
                command payload.

        Returns:
            ``"open"`` or ``"closed"`` when the command name is recognized,
            otherwise None.
        """
        name = str(command_name or "").strip().lower()
        if name in self.OPEN_COMMAND_NAMES:
            return "open"
        if name in self.CLOSE_COMMAND_NAMES:
            return "closed"
        return None

    def _device_is_live_registered(self, device_id: str) -> bool:
        """Return whether a device is currently live-registered with backend data.

        The method first checks the attached backend device catalog proxy. If
        that is unavailable, it falls back to the presentation payload cache.

        Args:
            device_id: Canonical backend device identifier.

        Returns:
            True when the device is marked live-registered, otherwise False.
        """
        catalog = getattr(self, "backend_device_catalog", None)
        getter = getattr(catalog, "get_proxy", None)
        if callable(getter):
            proxy = getter(device_id)
            if proxy is not None:
                return bool(getattr(proxy, "live_registered", False))

        presentation = getattr(self, "backend_device_presentation", None)
        if isinstance(presentation, dict):
            for entry in presentation.get("devices", []):
                if not isinstance(entry, dict):
                    continue
                entry_id = str(entry.get("id") or entry.get("device_id") or "")
                if entry_id == device_id:
                    return bool(entry.get("live_registered", False))

        return False

    def _request_xv_command(self, valve_id: str, state: str, *, source: str) -> None:
        """Send a valve command request through the attached backend callback.

        The request includes an operator-action payload describing the SCADA
        source, and it marks the command as ``mock_only`` when the target device
        is not live-registered.

        Args:
            valve_id: Target valve identifier shown by the SCADA window.
            state: Requested target state.
            source: UI source tag used in the emitted operator-action payload.
        """
        logger.info(
            "[SCADA] Enter _request_xv_command valve=%s target=%s source=%s",
            valve_id,
            state,
            source,
        )
        if self.playback_mode:
            return

        normalized_state = self._normalize_state(state)
        command_name = self._state_to_command_name(normalized_state)
        if command_name is None:
            logger.warning(
                "[SCADA] Refusing to send XV command with unsupported state %s", state
            )
            return

        device_id = self._resolve_backend_device_id(valve_id)
        if not device_id:
            logger.warning("[SCADA] No backend device mapping for valve %s", valve_id)
            return

        request = getattr(self, "request_backend_command", None)
        if not callable(request):
            logger.warning(
                "[SCADA] request_backend_command is not attached yet for %s", valve_id
            )
            return

        mock_only = not self._device_is_live_registered(device_id)

        operator_action = {
            "action": "scada_xv_command",
            "source": source,
            "valve_id": valve_id,
            "device_id": device_id,
            "requested_state": normalized_state,
        }

        self.pending_xv_commands[valve_id] = normalized_state

        try:
            request(
                command_name,
                device_id=device_id,
                command_args=[],
                command_kwargs={},
                mock_only=mock_only,
                operator_action=operator_action,
            )
            logger.info(
                "[SCADA] Requested backend XV command %s for %s (%s), mock_only=%s",
                command_name,
                valve_id,
                device_id,
                mock_only,
            )
        except Exception:
            logger.exception(
                "[SCADA] Failed to request backend XV command for %s", valve_id
            )

    def _sync_all_states_to_svg(self) -> None:
        """Push all cached valve states into the SVG view."""
        for valve_id, state in self.xv_states.items():
            self._push_state_to_svg(valve_id, state)

    def _push_state_to_svg(self, valve_id: str, state: str) -> None:
        """Apply a valve state to the embedded SVG view.

        Args:
            valve_id: SVG valve identifier.
            state: Raw or normalized valve state to render.
        """
        if self.web_view is None or not self._svg_loaded:
            return
        state = self._normalize_state(state)
        js = f"""
        (function() {{
            if (typeof setXVState === 'function') {{
                setXVState({valve_id!r}, {state!r});
                return true;
            }}
            console.warn('setXVState is not defined for SCADA playback/live view');
            return false;
        }})();
        """
        self.web_view.page().runJavaScript(js)

    def on_valve_clicked(self, valve_id: str) -> None:
        """Toggle a clicked SVG valve and request the matching backend command.

        Args:
            valve_id: SVG valve identifier emitted by the SCADA bridge.
        """
        logger.info("[SCADA] Valve clicked in window: %s", valve_id)
        if self.playback_mode:
            logger.info("[SCADA] Ignoring SVG click in playback mode: %s", valve_id)
            return

        current = self.xv_states.get(valve_id, "default")
        new_state = "open" if current in ("default", "closed") else "closed"
        logger.info("[SCADA] %s state change: %s -> %s", valve_id, current, new_state)
        self._request_xv_command(valve_id, new_state, source="scada_svg_click")

        # change the state immediately for better responsiveness, it will be corrected if the backend rejects the command
        # self.set_xv_state(valve_id, new_state)

    def set_xv_state(self, valve_id: str, state: str) -> None:
        """Update cached valve state and mirror it into the SVG.

        Args:
            valve_id: Valve identifier tracked by the SCADA window.
            state: Raw or normalized state value to store and render.
        """
        if valve_id not in self.xv_states:
            return
        state = self._normalize_state(state)
        self.xv_states[valve_id] = state
        logger.info("[SCADA] set_xv_state(%s, %s)", valve_id, state)
        self._push_state_to_svg(valve_id, state)

    def _extract_device_states(self, payload: dict[str, Any]) -> dict[str, str]:
        """Extract normalized valve states from a backend snapshot or event payload.

        The method understands the state shapes used by backend snapshots,
        telemetry sections, device-runtime sections, and ``command_out``
        structured events.

        Args:
            payload: Backend state snapshot or structured event payload.

        Returns:
            A mapping from tracked valve ids to normalized display states.
        """
        states: dict[str, str] = {}

        device_states = payload.get("device_states")
        if isinstance(device_states, dict):
            for valve_id, entry in device_states.items():
                if valve_id not in self.xv_states:
                    continue
                if isinstance(entry, dict):
                    state = entry.get("state") or entry.get("feedback_state")
                else:
                    state = entry
                states[valve_id] = self._normalize_state(state)

        telemetry = payload.get("telemetry")
        if isinstance(telemetry, dict):
            for valve_id in self.xv_device_ids:
                entry = telemetry.get(valve_id)
                if isinstance(entry, dict):
                    feedback_state = entry.get("feedback_state") or entry.get("state")
                    if feedback_state is not None:
                        states[valve_id] = self._normalize_state(feedback_state)

        device_runtime = payload.get("device_runtime")
        if isinstance(device_runtime, dict):
            runtime_by_id = device_runtime.get("by_id")
            if isinstance(runtime_by_id, dict):
                for device_id, entry in runtime_by_id.items():
                    if not isinstance(entry, dict):
                        continue
                    valve_id = self._resolve_svg_valve_id(device_id)
                    if valve_id is None:
                        continue

                    runtime_state = entry.get("runtime_state")
                    if runtime_state is None:
                        runtime_state = entry.get("state")
                    if runtime_state is None:
                        runtime_state = entry.get("feedback_state")
                    if runtime_state is None:
                        runtime_state = entry.get("runtime_status")

                    if runtime_state is not None:
                        states[valve_id] = self._normalize_state(runtime_state)

        event_kind = str(payload.get("event_kind") or "").strip().lower()
        if event_kind == "command_out":
            device_id = payload.get("device_id")
            valve_id = (
                self._resolve_svg_valve_id(device_id)
                if isinstance(device_id, str)
                else None
            )
            command_state = self._command_name_to_state(payload.get("command_name"))
            if valve_id is not None and command_state is not None:
                states[valve_id] = command_state

        return states

    def _apply_device_states(self, states: dict[str, str]) -> None:
        """Apply a batch of extracted valve states to the window.

        Args:
            states: Mapping from valve ids to normalized or raw state values.
        """
        for valve_id, state in states.items():
            self.set_xv_state(valve_id, state)

    def handle_playback_loaded(self, payload: dict[str, Any]) -> None:
        """Store playback load metadata and update the playback window title.

        Args:
            payload: Playback-load summary payload, optionally including
                metadata and run identifiers.
        """
        if not self.playback_mode or not isinstance(payload, dict):
            return
        self.playback_load_summary = dict(payload)
        metadata = payload.get("metadata")
        test_name = None
        if isinstance(metadata, dict):
            test_name = metadata.get("test_name") or metadata.get("run_id")
        if not test_name:
            test_name = payload.get("run_id") or self.test_name
        if isinstance(test_name, str) and test_name.strip():
            self.setWindowTitle(f"minTS SCADA - Playback - {test_name.strip()}")

    def handle_playback_seek_bootstrap(self, payload: dict[str, Any]) -> None:
        """Store playback seek bootstrap data and update the playback clock.

        Args:
            payload: Playback seek summary payload.
        """
        if not isinstance(payload, dict):
            return
        self.playback_seek_summary = dict(payload)
        seek_time = payload.get("seek_time_seconds")
        if isinstance(seek_time, (int, float)):
            self.playback_time = float(seek_time)

    def handle_backend_status(self, payload: dict[str, Any]) -> None:
        """Cache the backend run-status section from a backend status payload.

        Args:
            payload: Backend status payload that may include a ``run`` section.
        """
        if not isinstance(payload, dict):
            return
        run_payload = payload.get("run")
        if isinstance(run_payload, dict):
            self.backend_run_status = dict(run_payload)

    def apply_backend_state_snapshot(self, payload: dict[str, Any]) -> None:
        """Apply an authoritative backend state snapshot to the SCADA display.

        The method caches the snapshot, updates playback time when a playback
        clock is present, extracts valve states from the snapshot shape, and
        mirrors them into the SVG.

        Args:
            payload: Backend state snapshot payload.
        """
        if not isinstance(payload, dict):
            return
        self.backend_state_snapshot = dict(payload)
        playback_clock = payload.get("playback_clock")
        if isinstance(playback_clock, dict):
            position_seconds = playback_clock.get("position_seconds")
            if isinstance(position_seconds, (int, float)):
                self.playback_time = float(position_seconds)
        states = self._extract_device_states(payload)
        if states:
            self._apply_device_states(states)

    def handle_structured_event(self, payload: dict[str, Any]) -> None:
        """Apply SCADA-relevant structured events to valve display state.

        Only ``telemetry_in`` and ``command_out`` events are used for valve
        state extraction.

        Args:
            payload: Structured event payload from backend or playback.
        """
        if not isinstance(payload, dict):
            return
        event_kind = str(payload.get("event_kind") or "").strip().lower()
        if event_kind not in {"telemetry_in", "command_out"}:
            return
        states = self._extract_device_states(payload)
        if states:
            self._apply_device_states(states)

    def handle_command_result(self, payload: dict[str, Any]) -> None:
        """Clear pending command tracking after a backend command result arrives.

        Successful results only clear the pending entry. Failed results also log
        the backend rejection metadata for the affected valve.

        Args:
            payload: Backend command result payload.
        """
        if not isinstance(payload, dict):
            return

        device_id = payload.get("device_id")
        valve_id = (
            self._resolve_svg_valve_id(device_id)
            if isinstance(device_id, str)
            else None
        )
        if valve_id is None:
            return

        if bool(payload.get("success")):
            self.pending_xv_commands.pop(valve_id, None)
            return

        logger.warning(
            "[SCADA] Backend rejected XV command for %s (%s): status=%s error=%s rejection_reason=%s state_reasons=%s",
            valve_id,
            device_id,
            payload.get("status"),
            payload.get("error"),
            payload.get("rejection_reason"),
            payload.get("state_reasons"),
        )
        self.pending_xv_commands.pop(valve_id, None)

    def _on_abort_clicked(self) -> None:
        """Route the abort button through the relay callback when available."""
        if self.playback_mode:
            logger.info("[SCADA] Ignoring abort in playback mode")
            return
        trigger = getattr(self, "trigger_abort_via_relay", None)
        if callable(trigger):
            trigger()
            return
        self.abort()

    def _on_clear_abort_clicked(self) -> None:
        """Route the clear-abort-latch action through the relay callback.

        When the relay callback is unavailable, the method shows an error dialog
        instead of attempting a local fallback clear operation.
        """
        if self.playback_mode:
            logger.info("[SCADA] Ignoring clear abort latch in playback mode")
            return
        trigger = getattr(self, "trigger_clear_abort_latch_via_relay", None)
        if callable(trigger):
            trigger()
            return
        QMessageBox.critical(
            self,
            "Return to Normal Unavailable",
            "AbortRelay is not available for this SCADA window.",
        )

    def abort(self) -> None:
        """Show the local abort-unavailable fallback dialog."""
        logger.fatal("Abort triggered! Slap the big red button NOW!")
        QMessageBox.critical(
            self,
            "Abort Unavailable",
            "AbortRelay is not available for this SCADA window.",
        )

    def _snapshot_run_section(self) -> dict[str, Any]:
        """Return a copy of the cached backend snapshot ``run`` section.

        Returns:
            A copy of the cached run section, or an empty dictionary when the
            current backend snapshot does not include one.
        """
        snapshot = getattr(self, "backend_state_snapshot", None)
        if isinstance(snapshot, dict):
            run = snapshot.get("run")
            if isinstance(run, dict):
                return dict(run)
        return {}

    def _extract_run_id(self) -> str | None:
        """Extract the active run identifier from cached backend state.

        The method prefers the explicit backend run-status cache and then falls
        back to the ``run`` section of the cached full-state snapshot.

        Returns:
            The active run identifier when available, otherwise None.
        """
        run_status = getattr(self, "backend_run_status", None)
        if isinstance(run_status, dict):
            for key in ("run_id", "active_run_id"):
                value = run_status.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        run = self._snapshot_run_section()
        for key in ("active_run_id",):
            value = run.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _history_root(self) -> Path:
        """Return the project history root used for completed-run checks.

        Returns:
            The absolute path to the structured history root directory.
        """
        return Path(__file__).resolve().parent.parent / HISTORY_ROOT_DIRNAME

    def _complete_json_path(self) -> Path | None:
        """Return the completion-marker path for the active run.

        Returns:
            The ``complete.json`` path for the active run, or None when no run
            id is currently known.
        """
        run_id = self._extract_run_id()
        if not run_id:
            return None
        return self._history_root() / run_id / "complete.json"

    def _complete_json_exists(self) -> bool:
        """Return whether the active run already has a completion marker.

        Returns:
            True when the active run's ``complete.json`` file exists.
        """
        path = self._complete_json_path()
        return bool(path and path.exists())

    def _recording_active(self) -> bool:
        """Return whether cached backend state indicates an active recording.

        Returns:
            True when cached run status or snapshot data indicates the run is
            currently active.
        """
        run_status = getattr(self, "backend_run_status", None)
        if isinstance(run_status, dict):
            status = str(run_status.get("status") or "").strip().lower()
            if status in {"running", "recording", "active"}:
                return True
            if status in {"finished", "completed", "stopped", "idle", "not_running"}:
                return False
        run = self._snapshot_run_section()
        if "is_running" in run:
            return bool(run.get("is_running"))
        return False

    def _run_has_ever_started(self) -> bool:
        """Return whether cached run metadata shows a live run has started.

        Returns:
            True when a run id is present or the cached run section contains a
            non-empty start timestamp.
        """
        if self._extract_run_id():
            return True
        run = self._snapshot_run_section()
        started = run.get("last_started_wall_time")
        return isinstance(started, str) and bool(started.strip())

    def closeEvent(self, event) -> None:
        """Handle live and playback close behavior for the SCADA window.

        Live mode uses cached run state and history completion markers to decide
        whether closing should immediately shut down the application, warn that
        an unstarted run will be dropped, or keep the application open while
        finalization continues.

        Args:
            event: Qt close event supplied by the windowing system.
        """
        logger.info("[SCADA] ScadaWindow closing")

        if getattr(self, "_finalization_bypass", False):
            self._trigger_application_shutdown()
            event.accept()
            return

        if self.playback_mode:
            self._trigger_application_shutdown()
            event.accept()
            return

        if self._recording_active():
            event.accept()
            return

        if not self._run_has_ever_started():
            box = QMessageBox(self)
            box.setWindowTitle("Close Live Session")
            box.setIcon(QMessageBox.Warning)
            box.setText("This test will be dropped because no recording was started.")
            box.setInformativeText("Close the entire live application anyway?")
            close_btn = box.addButton("Close Application", QMessageBox.AcceptRole)
            cancel_btn = box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(cancel_btn)
            box.exec_()
            if box.clickedButton() is close_btn:
                self._trigger_application_shutdown()
                event.accept()
            else:
                event.ignore()
            return

        if self._complete_json_exists():
            self._trigger_application_shutdown()
            event.accept()
            return

        from gui.finalization_guard import (
            FinalizationWaitDialog,
            RESULT_COMPLETED,
            RESULT_FORCE_CLOSE,
            start_finalization_auto_close_timer,
        )

        dialog = FinalizationWaitDialog(self, self._complete_json_exists)
        dialog.exec_()

        if dialog.result_code in (RESULT_COMPLETED, RESULT_FORCE_CLOSE):
            self._trigger_application_shutdown()
            event.accept()
        else:
            start_finalization_auto_close_timer(self, self._complete_json_exists)
            event.ignore()

    def _trigger_application_shutdown(self) -> None:
        """Signal the application-wide shutdown watcher through the marker file."""
        try:
            shutdown_signal = (
                Path(__file__).resolve().parent.parent / ".shutdown_signal"
            )
            shutdown_signal.touch()
            logger.info("Triggered application shutdown signal")
        except Exception as exc:
            logger.warning("Failed to trigger shutdown signal: %s", exc)
