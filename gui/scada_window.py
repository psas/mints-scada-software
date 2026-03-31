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
    OPEN_COMMAND_NAMES = {"open", "open_valve", "valve_open"}
    CLOSE_COMMAND_NAMES = {"close", "close_valve", "valve_close"}

    def __init__(self, playback_mode: bool = False, test_name: str | None = None, manager=None):
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
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        diagram = QFrame()
        diagram.setStyleSheet("QFrame{background:#111; border:1px solid #444; border-radius:10px;}")
        dlay = QVBoxLayout(diagram)
        dlay.setContentsMargins(12, 12, 12, 12)

        svg_path = Path(__file__).resolve().parent.parent / "src/MinTS_SCADA_stable_v1_bridge_ready.svg"
        if svg_path.exists():
            self.web_view = QWebEngineView()
            self.web_view.setPage(ScadaWebPage(self.web_view))
            self.web_view.setStyleSheet("background:#111; border:none;")
            self.web_view.settings().setAttribute(QWebEngineSettings.JavascriptEnabled, True)
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

        btn_col = QFrame()
        btn_col.setFixedWidth(220)
        btn_col.setStyleSheet("QFrame{background:#2b2b2b; border:1px solid #444; border-radius:10px;}")
        blay = QVBoxLayout(btn_col)
        blay.setContentsMargins(16, 16, 16, 16)
        blay.setSpacing(14)

        self.open_26_button = QPushButton("Open LOX-XV-26")
        self.open_26_button.setMinimumHeight(72)
        self.open_26_button.clicked.connect(lambda: self._on_manual_button("lox-xv-26", "open"))
        blay.addWidget(self.open_26_button)

        self.close_26_button = QPushButton("Close LOX-XV-26")
        self.close_26_button.setMinimumHeight(72)
        self.close_26_button.clicked.connect(lambda: self._on_manual_button("lox-xv-26", "closed"))
        blay.addWidget(self.close_26_button)

        self.reset_button = QPushButton("Reset XV")
        self.reset_button.setMinimumHeight(72)
        self.reset_button.clicked.connect(self.reset_all_xv)
        blay.addWidget(self.reset_button)

        self.btn_abort = QPushButton("Abort")
        self.btn_abort.setMinimumHeight(72)
        self.btn_abort.clicked.connect(self._on_abort_clicked)
        blay.addWidget(self.btn_abort)

        self.debug_button = QPushButton("Print States")
        self.debug_button.setMinimumHeight(72)
        self.debug_button.clicked.connect(self.print_states)
        blay.addWidget(self.debug_button)

        for button in (
            self.open_26_button,
            self.close_26_button,
            self.reset_button,
            self.btn_abort,
            self.debug_button,
        ):
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
            if self.playback_mode:
                button.setEnabled(False)

        blay.addStretch()
        layout.addWidget(btn_col, 0)

    def _on_svg_loaded(self, ok: bool) -> None:
        self._svg_loaded = bool(ok)
        if not ok:
            logger.error("[SCADA] SVG web view failed to load")
            return
        logger.info("[SCADA] SVG web view finished loading")
        if self.playback_mode:
            self._apply_playback_lock_to_svg()
        self._sync_all_states_to_svg()
        if not self.playback_mode:
            request = getattr(self, "request_full_backend_state", None)
            if callable(request):
                try:
                    request()
                except Exception:
                    logger.debug("[SCADA] Could not request backend state on SVG load")

    def _apply_playback_lock_to_svg(self) -> None:
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
        if isinstance(state, bool):
            return "open" if state else "closed"

        value = str(state or "default").strip().lower()
        if value in {"open", "opened", "on", "true", "1", "commanded_open"}:
            return "open"
        if value in {"closed", "close", "shut", "off", "false", "0", "commanded_closed"}:
            return "closed"
        return "default"

    def _initial_valve_state(self, valve_id: str) -> str:
        """Compute initial display state: backend snapshot -> LIVE_STARTUP_STATE -> 'default'."""
        if self.backend_state_snapshot:
            states = self._extract_device_states(self.backend_state_snapshot)
            if valve_id in states:
                self._normalize_state(states[valve_id])
        startup = LIVE_STARTUP_STATE.get(valve_id)
        if startup is not None:
            return self._normalize_state(startup)
        return "default"

    def _resolve_backend_device_id(self, valve_id: str) -> str | None:
        return valve_id if valve_id in self.xv_states else None

    def _resolve_svg_valve_id(self, device_id: str) -> str | None:
        return device_id if device_id in self.xv_states else None

    def _state_to_command_name(self, state: str) -> str | None:
        normalized = self._normalize_state(state)
        if normalized == "open":
            return "open"
        if normalized == "closed":
            return "close"
        return None

    def _command_name_to_state(self, command_name: Any) -> str | None:
        name = str(command_name or "").strip().lower()
        if name in self.OPEN_COMMAND_NAMES:
            return "open"
        if name in self.CLOSE_COMMAND_NAMES:
            return "closed"
        return None

    def _device_is_live_registered(self, device_id: str) -> bool:
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
        logger.info("[SCADA] Enter _request_xv_command valve=%s target=%s source=%s", valve_id, state, source)
        if self.playback_mode:
            return

        normalized_state = self._normalize_state(state)
        command_name = self._state_to_command_name(normalized_state)
        if command_name is None:
            logger.warning("[SCADA] Refusing to send XV command with unsupported state %s", state)
            return

        device_id = self._resolve_backend_device_id(valve_id)
        if not device_id:
            logger.warning("[SCADA] No backend device mapping for valve %s", valve_id)
            return

        request = getattr(self, "request_backend_command", None)
        if not callable(request):
            logger.warning("[SCADA] request_backend_command is not attached yet for %s", valve_id)
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
            logger.exception("[SCADA] Failed to request backend XV command for %s", valve_id)

    def _sync_all_states_to_svg(self) -> None:
        for valve_id, state in self.xv_states.items():
            self._push_state_to_svg(valve_id, state)

    def _push_state_to_svg(self, valve_id: str, state: str) -> None:
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

    def _on_manual_button(self, valve_id: str, state: str) -> None:
        logger.info("[SCADA] Manual button pressed: %s -> %s", valve_id, state)
        if self.playback_mode:
            logger.info("[SCADA] Ignoring manual button click in playback mode: %s -> %s", valve_id, state)
            return
        self._request_xv_command(valve_id, state, source="scada_manual_button")
        # self.set_xv_state(valve_id, state)

    def on_valve_clicked(self, valve_id: str) -> None:
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
        if valve_id not in self.xv_states:
            return
        state = self._normalize_state(state)
        self.xv_states[valve_id] = state
        logger.info("[SCADA] set_xv_state(%s, %s)", valve_id, state)
        self._push_state_to_svg(valve_id, state)

    def _extract_device_states(self, payload: dict[str, Any]) -> dict[str, str]:
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
            valve_id = self._resolve_svg_valve_id(device_id) if isinstance(device_id, str) else None
            command_state = self._command_name_to_state(payload.get("command_name"))
            if valve_id is not None and command_state is not None:
                states[valve_id] = command_state

        return states

    def _apply_device_states(self, states: dict[str, str]) -> None:
        for valve_id, state in states.items():
            # if valve_id in self.pending_xv_commands:
            #     continue
            self.set_xv_state(valve_id, state)

    def handle_playback_loaded(self, payload: dict[str, Any]) -> None:
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
        if not isinstance(payload, dict):
            return
        self.playback_seek_summary = dict(payload)
        seek_time = payload.get("seek_time_seconds")
        if isinstance(seek_time, (int, float)):
            self.playback_time = float(seek_time)

    def handle_backend_status(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        run_payload = payload.get("run")
        if isinstance(run_payload, dict):
            self.backend_run_status = dict(run_payload)

    def apply_backend_state_snapshot(self, payload: dict[str, Any]) -> None:
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
        if not isinstance(payload, dict):
            return
        event_kind = str(payload.get("event_kind") or "").strip().lower()
        if event_kind not in {"telemetry_in", "command_out"}:
            return
        states = self._extract_device_states(payload)
        if states:
            self._apply_device_states(states)

    def handle_command_result(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return

        device_id = payload.get("device_id")
        valve_id = self._resolve_svg_valve_id(device_id) if isinstance(device_id, str) else None
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

    def reset_all_xv(self) -> None:
        if self.playback_mode:
            logger.info("[SCADA] Ignoring reset in playback mode")
            return
        logger.info("[SCADA] Reset all XV to default")
        for valve_id in list(self.xv_states.keys()):
            self.set_xv_state(valve_id, "default")

    def print_states(self) -> None:
        logger.info("[SCADA] XV states: %s", self.xv_states)

    def _on_abort_clicked(self) -> None:
        if self.playback_mode:
            logger.info("[SCADA] Ignoring abort in playback mode")
            return
        trigger = getattr(self, "trigger_abort_via_relay", None)
        if callable(trigger):
            trigger()
            return
        self.abort()

    def abort(self) -> None:
        logger.fatal("Abort triggered! Slap the big red button NOW!")
        QMessageBox.critical(
            self,
            "Abort Unavailable",
            "AbortRelay is not available for this SCADA window.",
        )

    def _snapshot_run_section(self) -> dict[str, Any]:
        snapshot = getattr(self, "backend_state_snapshot", None)
        if isinstance(snapshot, dict):
            run = snapshot.get("run")
            if isinstance(run, dict):
                return dict(run)
        return {}

    def _extract_run_id(self) -> str | None:
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
        return Path(__file__).resolve().parent.parent / HISTORY_ROOT_DIRNAME

    def _complete_json_path(self) -> Path | None:
        run_id = self._extract_run_id()
        if not run_id:
            return None
        return self._history_root() / run_id / "complete.json"

    def _complete_json_exists(self) -> bool:
        path = self._complete_json_path()
        return bool(path and path.exists())

    def _recording_active(self) -> bool:
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
        if self._extract_run_id():
            return True
        run = self._snapshot_run_section()
        started = run.get("last_started_wall_time")
        return isinstance(started, str) and bool(started.strip())

    def closeEvent(self, event) -> None:
        logger.info("[SCADA] ScadaWindow closing")
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

        box = QMessageBox(self)
        box.setWindowTitle("Saving In Progress")
        box.setIcon(QMessageBox.Warning)
        box.setText(
            "Saving is in progress. Please wait patiently.\n\n"
            "If you click Terminate Anyway, it will terminate the saving process and crash the test."
        )
        wait_btn = box.addButton("Wait", QMessageBox.RejectRole)
        terminate_btn = box.addButton("Terminate Anyway", QMessageBox.DestructiveRole)
        box.setDefaultButton(wait_btn)
        box.exec_()
        if box.clickedButton() is terminate_btn:
            self._trigger_application_shutdown()
            event.accept()
        else:
            event.ignore()

    def _trigger_application_shutdown(self) -> None:
        try:
            shutdown_signal = Path(__file__).resolve().parent.parent / ".shutdown_signal"
            shutdown_signal.touch()
            logger.info("Triggered application shutdown signal")
        except Exception as exc:
            logger.warning("Failed to trigger shutdown signal: %s", exc)
