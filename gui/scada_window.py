# scada_window.py
from pathlib import Path
import logging
import re

from PyQt5.QtCore import QUrl
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

from gui.scada_bridge import ScadaBridge
from gui.scada_webpage import ScadaWebPage

logger = logging.getLogger(__name__)


class ScadaWindow(QMainWindow):
    def __init__(self, playback_mode=False, test_name=None, manager=None):
        super().__init__()
        self.manager = manager
        self.playback_mode = playback_mode
        self.test_name = test_name

        self.setWindowTitle("minTS SCADA - Right Screen")
        self.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyqt5"))

        self.xv_states = {
            "xv-23": "default",
            "xv-24": "default",
            "xv-25": "default",
            "xv-26": "default",
            "xv-27": "default",
        }

        central = QWidget()
        self.setCentralWidget(central)

        layout = QHBoxLayout(central)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        # Left side: SCADA diagram panel
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

            # WebChannel bridge
            self.bridge = ScadaBridge(self)
            self.bridge.valve_clicked.connect(self.on_valve_clicked)

            self.channel = QWebChannel(self.web_view.page())
            self.channel.registerObject("bridge", self.bridge)
            self.web_view.page().setWebChannel(self.channel)

            svg_text = svg_path.read_text(encoding="utf-8")
            svg_text = re.sub(r"<\?xml[^>]*\?>", "", svg_text, flags=re.IGNORECASE)
            svg_text = re.sub(r"<!DOCTYPE[^>]*>", "", svg_text, flags=re.IGNORECASE)

            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
                <style>
                    html, body {{
                        margin: 0;
                        padding: 0;
                        width: 100%;
                        height: 100%;
                        background: #111;
                        overflow: hidden;
                    }}

                    .wrap {{
                        width: 100%;
                        height: 100%;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        background: #111;
                    }}

                    .wrap > svg {{
                        width: 100%;
                        height: 100%;
                        display: block;
                        background: #111;
                    }}
                </style>
            </head>
            <body>
                <div class="wrap">
                    {svg_text}
                </div>

                <script>
                    window.bridge = null;

                    new QWebChannel(qt.webChannelTransport, function(channel) {{
                        window.bridge = channel.objects.bridge;
                        console.log("QWebChannel connected");
                    }});
                </script>
            </body>
            </html>
            """

            base_url = QUrl.fromLocalFile(str(svg_path.parent) + "/")
            self.web_view.setHtml(html, base_url)
            dlay.addWidget(self.web_view)

            logger.info("[SCADA] Loaded SVG: %s", svg_path)
        else:
            error_label = QLabel(f"SVG file not found:\\n{svg_path}")
            error_label.setStyleSheet("color:#bbb; font-size:16px;")
            dlay.addWidget(error_label)
            logger.error("[SCADA] SVG file not found: %s", svg_path)

        layout.addWidget(diagram, 1)

        # Right side: button column
        btn_col = QFrame()
        btn_col.setFixedWidth(220)
        btn_col.setStyleSheet(
            "QFrame{background:#2b2b2b; border:1px solid #444; border-radius:10px;}"
        )

        blay = QVBoxLayout(btn_col)
        blay.setContentsMargins(16, 16, 16, 16)
        blay.setSpacing(14)

        test_open_26 = QPushButton("Open XV-26")
        test_open_26.setMinimumHeight(72)
        test_open_26.clicked.connect(lambda: self.set_xv_state("xv-26", "open"))
        blay.addWidget(test_open_26)

        test_close_26 = QPushButton("Close XV-26")
        test_close_26.setMinimumHeight(72)
        test_close_26.clicked.connect(lambda: self.set_xv_state("xv-26", "closed"))
        blay.addWidget(test_close_26)

        reset_all = QPushButton("Reset XV")
        reset_all.setMinimumHeight(72)
        reset_all.clicked.connect(self.reset_all_xv)
        blay.addWidget(reset_all)

        debug_btn = QPushButton("Print States")
        debug_btn.setMinimumHeight(72)
        debug_btn.clicked.connect(self.print_states)
        blay.addWidget(debug_btn)

        for button in (test_open_26, test_close_26, reset_all, debug_btn):
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
                QPushButton:hover{
                    background:#7b1fa2;
                }
                QPushButton:pressed{
                    background:#6a1b9a;
                }
                """
            )

        blay.addStretch()
        layout.addWidget(btn_col, 0)

    def on_valve_clicked(self, valve_id: str):
        logger.info("[SCADA] Valve clicked in window: %s", valve_id)

        current = self.xv_states.get(valve_id, "default")

        if current in ("default", "closed"):
            new_state = "open"
        else:
            new_state = "closed"

        logger.info("[SCADA] %s state change: %s -> %s", valve_id, current, new_state)

        self.xv_states[valve_id] = new_state
        self.set_xv_state(valve_id, new_state)

        # future add real action
        # Such as:
        # self.send_solenoid_command(valve_id, new_state)

    def set_xv_state(self, valve_id: str, state: str):
        self.xv_states[valve_id] = state
        logger.info("[SCADA] set_xv_state(%s, %s)", valve_id, state)

        js = f"setXVState('{valve_id}', '{state}');"
        self.web_view.page().runJavaScript(js)

    def reset_all_xv(self):
        logger.info("[SCADA] Reset all XV to default")
        for valve_id in list(self.xv_states.keys()):
            self.set_xv_state(valve_id, "default")

    def print_states(self):
        logger.info("[SCADA] XV states: %s", self.xv_states)

    def _snapshot_run_section(self) -> dict:
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

    def closeEvent(self, event):
        logger.info("[SCADA] ScadaWindow closing")

        if self.playback_mode:
            self._trigger_application_shutdown()
            event.accept()
            return

        if self._recording_active():
            # While actively recording, closing one window should behave like an
            # accidental close and let the supervisor respawn it.
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
        """Trigger full application shutdown via shutdown watcher."""
        try:
            shutdown_signal = Path(__file__).resolve().parent.parent / ".shutdown_signal"
            shutdown_signal.touch()
            logger.info("Triggered application shutdown signal")
        except Exception as exc:
            logger.warning("Failed to trigger shutdown signal: %s", exc)