from pathlib import Path
import json
import os
import socket

from gui.playback_catalog import PlaybackRunSummary, discover_playback_runs

from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
    QApplication,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QPlainTextEdit,
    QFormLayout,
    QMessageBox,
    QComboBox,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor, QBrush
import qdarkstyle
import logging

from historymanager.rebuild import get_rebuild_artifact_status, publish_run_rebuild_artifacts
from historymanager.paths import HISTORY_ROOT_DIRNAME

"""
Startup Checklist Window
Performs pre-flight checks before launching main application
"""

log = logging.getLogger("checklist")

_INTEGRITY_BADGE_STYLES: dict[str, tuple[str, str, str]] = {
    "green": ("All data matches natively", "#4CAF50", "#16301b"),
    "yellow": ("Missing source, but rest data matches", "#FFC107", "#3a3211"),
    "red": ("Data does not match", "#F44336", "#3a1a1a"),
}

_INTEGRITY_ITEM_PREFIX: dict[str, str] = {
    "green": "[OK]",
    "yellow": "[CHECK]",
    "red": "[MISMATCH]",
}

_PLAYBACK_SOURCE_NATIVE = "native"
_PLAYBACK_SOURCE_REBUILD = "rebuild"
_REBUILD_SELECTION_PREFIX = "rebuild::"


class ChecklistItem(QWidget):
    """Individual checklist item with status indicator"""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(10, 5, 10, 5)

        self.status_label = QLabel("○")
        self.status_label.setFont(QFont("Arial", 16))
        self.status_label.setFixedWidth(30)
        self.layout.addWidget(self.status_label)

        self.text_label = QLabel(text)
        self.text_label.setFont(QFont("Arial", 11))
        self.layout.addWidget(self.text_label)

        self.result_label = QLabel("")
        self.result_label.setFont(QFont("Arial", 9))
        self.result_label.setStyleSheet("color: #888;")
        self.layout.addWidget(self.result_label)

        self.layout.addStretch()

        self.status = "pending"  # pending, checking, pass, fail
        self._update_display()

    def set_checking(self):
        self.status = "checking"
        self._update_display()

    def set_pass(self, message=""):
        self.status = "pass"
        if message:
            self.result_label.setText(message)
        self._update_display()

    def set_fail(self, message=""):
        self.status = "fail"
        if message:
            self.result_label.setText(message)
        self._update_display()

    def _update_display(self):
        if self.status == "pending":
            self.status_label.setText("○")
            self.status_label.setStyleSheet("color: #555;")
        elif self.status == "checking":
            self.status_label.setText("◐")
            self.status_label.setStyleSheet("color: #FFA726;")
        elif self.status == "pass":
            self.status_label.setText("●")
            self.status_label.setStyleSheet("color: #4CAF50;")
        elif self.status == "fail":
            self.status_label.setText("●")
            self.status_label.setStyleSheet("color: #F44336;")


class ChecklistWindow(QDialog):
    """
    Pre-flight checklist window.

    Supports two startup paths:
    - live mode: collect run metadata before backend start_run
    - playback mode: select a recorded run from ignitionhistory
    """

    def __init__(
        self,
        serial_port,
        parent=None,
        *,
        backend_socket_path: str | Path | None = None,
        auto_refresh_ms: int = 2000,
    ):
        super().__init__(parent)
        self.serial_port = serial_port
        self.backend_socket_path = (
            Path(backend_socket_path).expanduser().resolve()
            if backend_socket_path
            else self._default_backend_socket_path()
        )
        self.backend_probe_snapshot: dict[str, object] | None = None
        self._check_refresh_ms = max(500, int(auto_refresh_ms))
        self.all_passed = False
        self.selected_test = None
        self.playback_mode = False
        self.live_run_metadata: dict[str, str] | None = None
        self.playback_integrity_reports: dict[str, dict[str, object]] = {}
        self.playback_run_summaries_by_dir: dict[str, object] = {}
        self.playback_rebuild_status_by_dir: dict[str, dict[str, object]] = {}
        self.selected_playback_source: str = _PLAYBACK_SOURCE_NATIVE
        self.playback_continue_button: QPushButton | None = None
        self.live_continue_button: QPushButton | None = None
        self._live_init_in_progress = False

        self.setWindowTitle("minTS Controller - Startup Checklist")
        self.setGeometry(100, 100, 640, 460)

        QApplication.setStyle("Fusion")
        self.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyqt5"))

        self.main_layout = QVBoxLayout(self)

        self.checklist_widget = self._build_checklist_widget()
        self.main_layout.addWidget(self.checklist_widget)

        self._check_refresh_timer = QTimer(self)
        self._check_refresh_timer.setInterval(self._check_refresh_ms)
        self._check_refresh_timer.timeout.connect(self._maybe_refresh_checks)
        self._check_refresh_timer.start()

        QTimer.singleShot(500, self.run_checks)

    def _build_checklist_widget(self) -> QWidget:
        widget = QWidget()
        checklist_layout = QVBoxLayout(widget)
        checklist_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("System Pre-Flight Checklist")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        checklist_layout.addWidget(title)

        subtitle = QLabel("Checking hardware readiness and backend live status...")
        subtitle.setFont(QFont("Arial", 10))
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #888; margin-bottom: 20px;")
        checklist_layout.addWidget(subtitle)

        self.check_serial = ChecklistItem("Serial port connection")
        self.check_bus = ChecklistItem("CAN bus initialization")
        self.check_devices = ChecklistItem("Device communication")

        checklist_layout.addWidget(self.check_serial)
        checklist_layout.addWidget(self.check_bus)
        checklist_layout.addWidget(self.check_devices)

        checklist_layout.addStretch()

        self.status_message = QLabel("")
        self.status_message.setFont(QFont("Arial", 10))
        self.status_message.setAlignment(Qt.AlignCenter)
        self.status_message.setWordWrap(True)
        self.status_message.setStyleSheet("margin: 10px; padding: 10px;")
        checklist_layout.addWidget(self.status_message)

        button_layout = QHBoxLayout()

        self.playback_button = QPushButton("Playback")
        self.playback_button.clicked.connect(self.show_playback_selection)
        self.playback_button.setMinimumWidth(100)
        button_layout.addWidget(self.playback_button)

        button_layout.addStretch()

        self.continue_button = QPushButton("Live")
        self.continue_button.clicked.connect(self.show_live_setup)
        self.continue_button.setEnabled(False)
        self.continue_button.setMinimumWidth(100)
        button_layout.addWidget(self.continue_button)

        self.exit_button = QPushButton("Exit")
        self.exit_button.clicked.connect(self.reject)
        self.exit_button.setMinimumWidth(100)
        button_layout.addWidget(self.exit_button)

        checklist_layout.addLayout(button_layout)
        return widget

    def _build_live_setup_widget(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Live Run Setup")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Enter live run metadata before opening the operator windows.")
        subtitle.setFont(QFont("Arial", 10))
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #888; margin-bottom: 20px;")
        layout.addWidget(subtitle)

        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        form_layout.setContentsMargins(30, 10, 30, 10)
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignRight)

        self.test_name_input = QLineEdit()
        self.test_name_input.setPlaceholderText("Example: ignition_test_01")
        form_layout.addRow("Test name", self.test_name_input)

        self.operator_input = QLineEdit()
        self.operator_input.setPlaceholderText("Operator name")
        form_layout.addRow("Operator", self.operator_input)

        self.profile_input = QLineEdit()
        self.profile_input.setPlaceholderText("Optional profile name")
        form_layout.addRow("Profile", self.profile_input)

        self.notes_input = QPlainTextEdit()
        self.notes_input.setPlaceholderText("Optional run notes")
        self.notes_input.setMinimumHeight(120)
        form_layout.addRow("Notes", self.notes_input)

        layout.addWidget(form_widget)

        self.live_setup_status = QLabel(
            "Required: test name and operator. Optional: profile and notes."
        )
        self.live_setup_status.setWordWrap(True)
        self.live_setup_status.setAlignment(Qt.AlignCenter)
        self.live_setup_status.setStyleSheet("color: #888; margin: 10px; padding: 10px;")
        layout.addWidget(self.live_setup_status)

        button_layout = QHBoxLayout()

        back_button = QPushButton("Back")
        back_button.clicked.connect(self.show_checklist)
        back_button.setMinimumWidth(100)
        button_layout.addWidget(back_button)

        button_layout.addStretch()

        self.live_continue_button = QPushButton("Continue")
        self.live_continue_button.clicked.connect(self.on_live_selected)
        self.live_continue_button.setEnabled(False)
        self.live_continue_button.setMinimumWidth(120)
        button_layout.addWidget(self.live_continue_button)

        exit_button = QPushButton("Exit")
        exit_button.clicked.connect(self.reject)
        exit_button.setMinimumWidth(100)
        button_layout.addWidget(exit_button)

        layout.addLayout(button_layout)

        self.test_name_input.textChanged.connect(self._update_live_continue_state)
        self.operator_input.textChanged.connect(self._update_live_continue_state)
        self.test_name_input.returnPressed.connect(self._maybe_submit_live_setup)
        self.operator_input.returnPressed.connect(self._maybe_submit_live_setup)
        self.profile_input.returnPressed.connect(self._maybe_submit_live_setup)

        return widget

    def run_checks(self):
        """Run all pre-flight checks using backend-owned live readiness."""
        self.continue_button.setEnabled(False)
        self.status_message.setText("Running checks...")
        self.status_message.setStyleSheet("color: #888; margin: 10px; padding: 10px;")

        self.check_serial.set_checking()
        QApplication.processEvents()

        serial_ok = Path(self.serial_port).exists()
        if serial_ok:
            self.check_serial.set_pass(f"Found: {self.serial_port}")
            log.info("Serial port check passed: %s", self.serial_port)
        else:
            self.check_serial.set_fail(f"Not found: {self.serial_port}")
            log.error("Serial port not found: %s", self.serial_port)

        self.check_bus.set_checking()
        QApplication.processEvents()
        probe = self._probe_backend_live_state()
        self.backend_probe_snapshot = (
            probe.get("snapshot") if isinstance(probe.get("snapshot"), dict) else None
        )

        bus_ok = False
        devices_ok = False
        bus_message = "Backend live status unavailable"
        devices_message = "Backend live status unavailable"

        if probe.get("reachable"):
            snapshot = probe.get("snapshot") if isinstance(probe.get("snapshot"), dict) else {}
            bus_state = snapshot.get("bus") if isinstance(snapshot.get("bus"), dict) else {}
            registry_state = (
                snapshot.get("device_registry")
                if isinstance(snapshot.get("device_registry"), dict)
                else {}
            )

            bus_connected = bool(bus_state.get("connected"))
            bus_reconnecting = bool(bus_state.get("reconnecting"))
            sender = str(bus_state.get("sender") or "backend")
            bitrate = bus_state.get("bitrate")
            bitrate_text = f" @ {bitrate}" if bitrate else ""

            if bus_connected and not bus_reconnecting:
                bus_ok = True
                bus_message = f"Ready via {sender}{bitrate_text}"
            elif bus_reconnecting:
                bus_message = "Backend is reconnecting the live bus"
            else:
                bus_message = "Backend is reachable, but live bus is not connected"

            total_devices = int(registry_state.get("total_devices") or 0)
            load_error_count = int(registry_state.get("load_error_count") or 0)

            if bus_ok and total_devices > 0 and load_error_count == 0:
                devices_ok = True
                devices_message = f"{total_devices} device(s) available"
            elif load_error_count > 0:
                devices_message = f"{load_error_count} device load error(s)"
            elif total_devices > 0:
                devices_message = f"{total_devices} device(s) listed, waiting for live readiness"
            else:
                devices_message = "No devices available from backend registry"
        else:
            bus_message = str(
                probe.get("message") or f"Backend service unavailable at {self.backend_socket_path}"
            )
            devices_message = "Device readiness unavailable until backend responds"

        if bus_ok:
            self.check_bus.set_pass(bus_message)
        else:
            self.check_bus.set_fail(bus_message)

        self.check_devices.set_checking()
        QApplication.processEvents()
        if devices_ok:
            self.check_devices.set_pass(devices_message)
        else:
            self.check_devices.set_fail(devices_message)

        if serial_ok and bus_ok and devices_ok:
            self._handle_success()
        else:
            failure_parts: list[str] = []
            if not serial_ok:
                failure_parts.append("serial port not found")
            if not bus_ok:
                failure_parts.append(bus_message)
            if not devices_ok:
                failure_parts.append(devices_message)
            self._handle_failure("; ".join(failure_parts))

    def _handle_success(self):
        self.all_passed = True
        self.status_message.setText(
            "All checks passed. Live mode is ready through backend-owned hardware state."
        )
        self.status_message.setStyleSheet(
            "color: #4CAF50; margin: 10px; padding: 10px; font-weight: bold;"
        )
        self.continue_button.setEnabled(True)
        log.info("All pre-flight checks passed")

    def _handle_failure(self, message):
        self.all_passed = False
        self.status_message.setText(
            f"Check failed: {message}\n\nPlayback is still available. "
            f"Live mode will unlock when backend live readiness is available."
        )
        self.status_message.setStyleSheet(
            "color: #F44336; margin: 10px; padding: 10px; "
            "background-color: #3a1a1a; border-radius: 5px;"
        )
        log.error("Pre-flight check failed: %s", message)

    def show_live_setup(self):
        """Switch to live run metadata entry view."""
        self.run_checks()

        if not self.all_passed:
            self.status_message.setText("Attempting to initialize live hardware through backend...")
            self.status_message.setStyleSheet("color: #FFA726; margin: 10px; padding: 10px;")
            QApplication.processEvents()

            init_ok, init_message = self._initialize_backend_live_hardware()
            if init_ok:
                log.info("Checklist-triggered live hardware init succeeded: %s", init_message)
            else:
                log.error("Checklist-triggered live hardware init failed: %s", init_message)

            self.run_checks()

        if not self.all_passed:
            QMessageBox.warning(
                self,
                "Checks Not Complete",
                "All pre-flight checks must pass before starting live mode.",
            )
            return

        self.checklist_widget.hide()

        if not hasattr(self, "live_setup_widget"):
            self.live_setup_widget = self._build_live_setup_widget()
            self.main_layout.addWidget(self.live_setup_widget)

        self.playback_mode = False
        self.live_setup_widget.show()
        self._update_live_continue_state()
        self.test_name_input.setFocus()

    def show_playback_selection(self):
        """Switch to playback run selection view"""
        self.checklist_widget.hide()
        if hasattr(self, "live_setup_widget"):
            self.live_setup_widget.hide()

        self.playback_widget = QWidget()
        playback_layout = QVBoxLayout(self.playback_widget)
        playback_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Select Run to Playback")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        playback_layout.addWidget(title)

        subtitle = QLabel(
            f"Choose a run from {HISTORY_ROOT_DIRNAME}. Select a run first, then click Continue."
        )
        subtitle.setFont(QFont("Arial", 10))
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #888; margin-bottom: 20px;")
        playback_layout.addWidget(subtitle)

        self.test_list = QListWidget()
        self.test_list.setFont(QFont("Arial", 11))
        self.test_list.setSelectionMode(QListWidget.SingleSelection)
        self.test_list.currentItemChanged.connect(self.on_playback_item_changed)
        playback_layout.addWidget(self.test_list)

        integrity_panel = QWidget()
        integrity_layout = QVBoxLayout(integrity_panel)
        integrity_layout.setContentsMargins(0, 8, 0, 0)

        self.integrity_badge_label = QLabel("Integrity status will appear here.")
        self.integrity_badge_label.setAlignment(Qt.AlignCenter)
        self.integrity_badge_label.setWordWrap(True)
        self.integrity_badge_label.setStyleSheet(
            "padding: 8px; border-radius: 6px; color: #ddd; background-color: #1f1f1f;"
        )
        integrity_layout.addWidget(self.integrity_badge_label)

        self.integrity_details_box = QPlainTextEdit()
        self.integrity_details_box.setReadOnly(True)
        self.integrity_details_box.setMinimumHeight(140)
        self.integrity_details_box.setPlaceholderText(
            "Select a run to view archive integrity details."
        )
        integrity_layout.addWidget(self.integrity_details_box)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Playback source"))

        self.playback_source_combo = QComboBox()
        self.playback_source_combo.addItem("Native archive", _PLAYBACK_SOURCE_NATIVE)
        self.playback_source_combo.setEnabled(False)
        source_row.addWidget(self.playback_source_combo, 1)

        self.prepare_rebuild_button = QPushButton("Prepare Rebuild")
        self.prepare_rebuild_button.setEnabled(False)
        self.prepare_rebuild_button.clicked.connect(self.on_prepare_rebuild_clicked)
        source_row.addWidget(self.prepare_rebuild_button)
        integrity_layout.addLayout(source_row)

        self.rebuild_status_label = QLabel(
            "Rebuild artifacts are not prepared for the selected run."
        )
        self.rebuild_status_label.setWordWrap(True)
        self.rebuild_status_label.setStyleSheet("color: #999; margin-top: 4px;")
        integrity_layout.addWidget(self.rebuild_status_label)

        playback_layout.addWidget(integrity_panel)

        self._load_available_tests()

        button_layout = QHBoxLayout()

        back_button = QPushButton("Back")
        back_button.clicked.connect(self.show_checklist)
        back_button.setMinimumWidth(100)
        button_layout.addWidget(back_button)

        button_layout.addStretch()

        self.playback_continue_button = QPushButton("Continue")
        self.playback_continue_button.clicked.connect(self.on_test_selected)
        self.playback_continue_button.setEnabled(False)
        self.playback_continue_button.setMinimumWidth(100)
        button_layout.addWidget(self.playback_continue_button)

        exit_button = QPushButton("Exit")
        exit_button.clicked.connect(self.reject)
        exit_button.setMinimumWidth(100)
        button_layout.addWidget(exit_button)

        playback_layout.addLayout(button_layout)

        self.main_layout.addWidget(self.playback_widget)
        self.playback_widget.show()

        if self.test_list.count() > 0 and self.test_list.item(0).flags() & Qt.ItemIsEnabled:
            self.test_list.setCurrentRow(0)

        self._update_playback_continue_button()

    def show_checklist(self):
        """Switch back to the main checklist view."""
        if hasattr(self, "playback_widget"):
            self.playback_widget.hide()
            self.main_layout.removeWidget(self.playback_widget)
            self.playback_widget.deleteLater()
            del self.playback_widget
            self.playback_continue_button = None

        if hasattr(self, "live_setup_widget"):
            self.live_setup_widget.hide()

        self.checklist_widget.show()

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def _default_backend_socket_path(self) -> Path:
        env_value = os.environ.get("MINTS_BACKEND_SOCKET")
        if env_value:
            return Path(env_value).expanduser().resolve()
        return (self._project_root() / ".backend_service.sock").resolve()

    def _maybe_refresh_checks(self) -> None:
        if self.checklist_widget.isVisible() and not self._live_init_in_progress:
            self.run_checks()

    def _probe_backend_live_state(self, *, timeout_s: float = 0.75) -> dict[str, object]:
        socket_path = self.backend_socket_path
        if not socket_path.exists():
            return {
                "reachable": False,
                "message": f"Backend socket not found: {socket_path}",
                "snapshot": None,
            }

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout_s)
                sock.connect(str(socket_path))

                hello_payload = {
                    "client_name": "checklist_window",
                    "window_role": "launcher",
                    "window_kind": "checklist",
                    "mode": "check",
                    "pid": os.getpid(),
                }
                self._send_probe_message(sock, "hello", hello_payload)
                self._send_probe_message(sock, "request_full_state", {})
                self._send_probe_message(sock, "status_request", {})

                snapshot: dict[str, object] | None = None
                backend_status: dict[str, object] | None = None
                buffer = ""

                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    buffer += chunk.decode("utf-8", errors="replace")

                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue

                        try:
                            message = json.loads(line)
                        except Exception:
                            continue

                        if not isinstance(message, dict):
                            continue

                        message_type = str(message.get("type") or "")
                        payload = (
                            message.get("payload")
                            if isinstance(message.get("payload"), dict)
                            else {}
                        )

                        if message_type == "state_snapshot":
                            snapshot = payload
                        elif message_type == "backend_status":
                            backend_status = payload

                        if snapshot is not None and backend_status is not None:
                            return {
                                "reachable": True,
                                "message": "Backend service responded",
                                "snapshot": snapshot,
                                "backend_status": backend_status,
                            }
        except Exception as exc:
            return {
                "reachable": False,
                "message": f"Backend service unavailable: {exc}",
                "snapshot": None,
            }

        return {
            "reachable": False,
            "message": "Backend service did not return state data",
            "snapshot": None,
        }

    def _initialize_backend_live_hardware(
        self,
        *,
        timeout_s: float = 2.0,
    ) -> tuple[bool, str]:
        socket_path = self.backend_socket_path

        if not socket_path.exists():
            return False, f"Backend socket not found: {socket_path}"

        self._live_init_in_progress = True
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout_s)
                sock.connect(str(socket_path))

                hello_payload = {
                    "client_name": "checklist_window",
                    "window_role": "launcher",
                    "window_kind": "checklist",
                    "mode": "live_init",
                    "pid": os.getpid(),
                }

                self._send_probe_message(sock, "hello", hello_payload)
                self._send_probe_message(sock, "initialize_live_hardware", {})
                self._send_probe_message(sock, "request_full_state", {})

                buffer = ""
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break

                    buffer += chunk.decode("utf-8", errors="replace")

                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue

                        try:
                            message = json.loads(line)
                        except Exception:
                            continue

                        if not isinstance(message, dict):
                            continue

                        message_type = str(message.get("type") or "")
                        payload = (
                            message.get("payload")
                            if isinstance(message.get("payload"), dict)
                            else {}
                        )

                        if message_type == "error":
                            return (
                                False,
                                str(payload.get("message") or "Live hardware initialization failed"),
                            )

                        if message_type == "hardware_status":
                            if bool(payload.get("connected")):
                                return True, "Live hardware initialized"

                        if message_type == "state_snapshot":
                            bus_state = payload.get("bus") if isinstance(payload.get("bus"), dict) else {}
                            if bool(bus_state.get("connected")):
                                return True, "Live hardware initialized"

        except Exception as exc:
            return False, f"Backend live initialization failed: {exc}"
        finally:
            self._live_init_in_progress = False

        return False, "Backend did not confirm live hardware initialization"

    def _send_probe_message(self, sock: socket.socket, message_type: str, payload: dict[str, object]) -> None:
        wire = json.dumps(
            {"type": message_type, "payload": payload},
            ensure_ascii=False,
            sort_keys=False,
        ) + "\n"
        sock.sendall(wire.encode("utf-8"))

    def _required_live_fields_present(self) -> bool:
        test_name = self.test_name_input.text().strip() if hasattr(self, "test_name_input") else ""
        operator = self.operator_input.text().strip() if hasattr(self, "operator_input") else ""
        return bool(test_name and operator)

    def _update_live_continue_state(self) -> None:
        if self.live_continue_button is None:
            return

        ready = self._required_live_fields_present()
        self.live_continue_button.setEnabled(ready)

        if ready:
            self.live_setup_status.setText(
                "Live metadata is ready. Click Continue to launch the live session."
            )
            self.live_setup_status.setStyleSheet("color: #4CAF50; margin: 10px; padding: 10px;")
        else:
            self.live_setup_status.setText(
                "Required: test name and operator. Optional: profile and notes."
            )
            self.live_setup_status.setStyleSheet("color: #888; margin: 10px; padding: 10px;")

    def _maybe_submit_live_setup(self) -> None:
        if self.live_continue_button is not None and self.live_continue_button.isEnabled():
            self.on_live_selected()

    def on_live_selected(self):
        """Validate live metadata and accept the dialog for live startup."""
        test_name = self.test_name_input.text().strip()
        operator = self.operator_input.text().strip()
        profile_name = self.profile_input.text().strip()
        notes = self.notes_input.toPlainText().strip()

        if not test_name:
            self.live_setup_status.setText("Test name is required.")
            self.live_setup_status.setStyleSheet(
                "color: #F44336; margin: 10px; padding: 10px;"
                "background-color: #3a1a1a; border-radius: 5px;"
            )
            self.test_name_input.setFocus()
            return

        if not operator:
            self.live_setup_status.setText("Operator is required.")
            self.live_setup_status.setStyleSheet(
                "color: #F44336; margin: 10px; padding: 10px;"
                "background-color: #3a1a1a; border-radius: 5px;"
            )
            self.operator_input.setFocus()
            return

        self.live_run_metadata = {
            "test_name": test_name,
            "mode": "live",
        }
        if operator:
            self.live_run_metadata["operator"] = operator
        if profile_name:
            self.live_run_metadata["profile_name"] = profile_name
        if notes:
            self.live_run_metadata["notes"] = notes

        self.playback_mode = False
        log.info("Selected live startup metadata: %s", self.live_run_metadata)
        self.accept()

    def _ignitionhistory_path(self) -> Path:
        return self._project_root() / HISTORY_ROOT_DIRNAME

    def _load_available_tests(self):
        """Load available playback runs from ignitionhistory folder"""
        self.test_list.clear()
        self.playback_integrity_reports.clear()
        self.playback_run_summaries_by_dir.clear()
        self.playback_rebuild_status_by_dir.clear()

        history_path = self._ignitionhistory_path()

        if not history_path.exists():
            item = QListWidgetItem("No playback runs available")
            item.setFlags(Qt.NoItemFlags)
            self.test_list.addItem(item)
            log.info("%s folder does not exist", history_path)
            self._set_integrity_placeholder("No playback runs available.")
            return

        try:
            run_summaries = discover_playback_runs(self._project_root(), include_integrity=True)

            if not run_summaries:
                item = QListWidgetItem("No playback runs available")
                item.setFlags(Qt.NoItemFlags)
                self.test_list.addItem(item)
                log.info("No run directories with metadata.json found in %s", history_path)
                self._set_integrity_placeholder("No playback runs available.")
                return

            for summary in run_summaries:
                run_dir_str = str(summary.run_dir)
                self.playback_run_summaries_by_dir[run_dir_str] = summary

                report = (
                    summary.integrity_report
                    if isinstance(summary.integrity_report, dict)
                    else self._scan_integrity_for_summary(summary)
                )
                self.playback_integrity_reports[run_dir_str] = report
                self.playback_rebuild_status_by_dir[run_dir_str] = self._load_rebuild_status(summary.run_dir)

                badge = summary.integrity_badge or str(report.get("badge") or "red")
                prefix = _INTEGRITY_ITEM_PREFIX.get(badge, "[CHECK]")
                item = QListWidgetItem(
                    f"{prefix} {summary.display_title}\n{summary.display_subtitle}"
                )
                item.setData(Qt.UserRole, run_dir_str)
                item.setData(Qt.UserRole + 1, report)
                item.setToolTip(self._build_list_item_tooltip(summary.tooltip_text, report))
                item.setForeground(QBrush(self._integrity_qcolor(badge)))
                self.test_list.addItem(item)

            log.info("Found %d playback runs in %s", len(run_summaries), history_path)

        except Exception as e:
            log.error("Error loading playback runs: %s", e)
            item = QListWidgetItem(f"Error loading playback runs: {e}")
            item.setFlags(Qt.NoItemFlags)
            self.test_list.addItem(item)
            self._set_integrity_placeholder(f"Error loading playback runs: {e}")

    def _is_selectable_playback_item(self, item: QListWidgetItem | None) -> bool:
        if item is None:
            return False
        if not (item.flags() & Qt.ItemIsEnabled):
            return False
        run_dir_str = item.data(Qt.UserRole)
        return isinstance(run_dir_str, str) and bool(run_dir_str.strip())

    def _update_playback_continue_button(self) -> None:
        if self.playback_continue_button is None:
            return
        self.playback_continue_button.setEnabled(
            self._is_selectable_playback_item(
                self.test_list.currentItem() if hasattr(self, "test_list") else None
            )
        )

    def on_playback_item_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None = None,
    ):
        del previous
        self._update_playback_continue_button()

        if current is None or not (current.flags() & Qt.ItemIsEnabled):
            self._set_integrity_placeholder("Select a run to view archive integrity details.")
            return

        report = current.data(Qt.UserRole + 1)
        if not isinstance(report, dict):
            run_dir_str = current.data(Qt.UserRole)
            if isinstance(run_dir_str, str):
                report = self.playback_integrity_reports.get(run_dir_str)
        if not isinstance(report, dict):
            self._set_integrity_placeholder("Integrity details are unavailable for this run.")
            return

        self._apply_integrity_report(report)

        run_dir_str = current.data(Qt.UserRole)
        rebuild_status = {}
        if isinstance(run_dir_str, str):
            rebuild_status = self.playback_rebuild_status_by_dir.get(run_dir_str, {})
        self._apply_rebuild_status(rebuild_status if isinstance(rebuild_status, dict) else {})

    def _scan_integrity_for_summary(self, summary: PlaybackRunSummary) -> dict[str, object]:
        report = summary.integrity_report
        if isinstance(report, dict):
            return report

        log.warning("Integrity details unavailable in playback summary for %s", summary.run_dir)
        return {
            "overall_status": summary.integrity_status or "unknown",
            "badge": summary.integrity_badge or "red",
            "summary_message": summary.integrity_summary_message or "Integrity details unavailable.",
            "stream_reports": {},
            "source_presence": {
                "raw": False,
                "rawbak": False,
                "history": False,
            },
        }

    def _apply_integrity_report(self, report: dict[str, object]) -> None:
        badge = str(report.get("badge") or "red")
        summary_message = str(report.get("summary_message") or "Integrity result unavailable.")
        badge_text, fg, bg = _INTEGRITY_BADGE_STYLES.get(
            badge,
            ("Integrity status unavailable", "#F44336", "#3a1a1a"),
        )
        self.integrity_badge_label.setText(f"{badge_text}\n{summary_message}")
        self.integrity_badge_label.setStyleSheet(
            f"padding: 8px; border-radius: 6px; color: {fg}; "
            f"background-color: {bg}; font-weight: bold;"
        )
        current_item = self.test_list.currentItem() if hasattr(self, "test_list") else None
        run_dir_str = current_item.data(Qt.UserRole) if current_item is not None else None
        rebuild_status = (
            self.playback_rebuild_status_by_dir.get(run_dir_str, {})
            if isinstance(run_dir_str, str)
            else {}
        )
        self.integrity_details_box.setPlainText(
            self._build_integrity_detail_text(report, rebuild_status)
        )

    def _set_integrity_placeholder(self, text: str) -> None:
        if hasattr(self, "integrity_badge_label"):
            self.integrity_badge_label.setText(text)
            self.integrity_badge_label.setStyleSheet(
                "padding: 8px; border-radius: 6px; color: #ddd; background-color: #1f1f1f;"
            )
        if hasattr(self, "integrity_details_box"):
            self.integrity_details_box.setPlainText("")
        if hasattr(self, "playback_source_combo"):
            self.playback_source_combo.blockSignals(True)
            self.playback_source_combo.clear()
            self.playback_source_combo.addItem("Native archive", _PLAYBACK_SOURCE_NATIVE)
            self.playback_source_combo.setEnabled(False)
            self.playback_source_combo.blockSignals(False)
        if self.playback_continue_button is not None:
            self.playback_continue_button.setEnabled(False)
        if hasattr(self, "prepare_rebuild_button"):
            self.prepare_rebuild_button.setEnabled(False)
        if hasattr(self, "rebuild_status_label"):
            self.rebuild_status_label.setText(
                "Rebuild artifacts are not prepared for the selected run."
            )

    def _build_list_item_tooltip(self, base_tooltip: str, report: dict[str, object]) -> str:
        parts = [base_tooltip]
        summary_message = report.get("summary_message")
        if isinstance(summary_message, str) and summary_message.strip():
            parts.extend(["", f"Integrity: {summary_message.strip()}"])
        return "\n".join(parts)

    def _build_integrity_detail_text(
        self,
        report: dict[str, object],
        rebuild_status: dict[str, object] | None = None,
    ) -> str:
        lines: list[str] = []

        overall_status = str(report.get("overall_status") or "unknown")
        summary_message = str(report.get("summary_message") or "Integrity result unavailable.")
        lines.append(f"Overall status: {overall_status}")
        lines.append(f"Summary: {summary_message}")

        source_presence = report.get("source_presence")
        if isinstance(source_presence, dict):
            present = [name for name, value in source_presence.items() if value]
            missing = [name for name, value in source_presence.items() if not value]
            lines.append(f"Sources present: {', '.join(present) if present else 'none'}")
            if missing:
                lines.append(f"Sources missing: {', '.join(missing)}")

        stream_reports = report.get("stream_reports")
        if isinstance(stream_reports, dict):
            for stream_name in ("telemetry_in", "command_out", "operator_action", "system_event"):
                stream_report = stream_reports.get(stream_name)
                if not isinstance(stream_report, dict):
                    continue

                lines.append("")
                lines.append(f"[{stream_name}]")
                lines.append(f"Status: {stream_report.get('status', 'unknown')}")
                lines.append(f"Message: {stream_report.get('message', '')}")

                missing_map = stream_report.get("missing_event_uid_sample_by_source")
                if isinstance(missing_map, dict) and missing_map:
                    missing_sources = ", ".join(sorted(missing_map.keys()))
                    lines.append(f"Missing event coverage in: {missing_sources}")

                if stream_report.get("hash_mismatch_count"):
                    lines.append(
                        f"Hash mismatches: {stream_report.get('hash_mismatch_count')}"
                    )

                if stream_report.get("stream_seq_mismatch_count"):
                    lines.append(
                        f"Sequence mismatches: {stream_report.get('stream_seq_mismatch_count')}"
                    )

                source_summaries = stream_report.get("source_summaries")
                if isinstance(source_summaries, dict):
                    for source_name in ("raw", "rawbak", "history"):
                        source_summary = source_summaries.get(source_name)
                        if not isinstance(source_summary, dict):
                            continue
                        present = source_summary.get("present", False)
                        count = source_summary.get("count", 0)
                        parse_errors = source_summary.get("parse_error_count", 0)
                        missing_identity = source_summary.get("missing_identity_count", 0)
                        lines.append(
                            f"  - {source_name}: present={present}, count={count}, "
                            f"parse_errors={parse_errors}, missing_identity={missing_identity}"
                        )

        if isinstance(rebuild_status, dict):
            self._append_rebuild_detail_lines(lines, rebuild_status)

        return "\n".join(lines)

    def _integrity_qcolor(self, badge: str) -> QColor:
        if badge == "green":
            return QColor("#4CAF50")
        if badge == "yellow":
            return QColor("#FFC107")
        return QColor("#F44336")

    def on_test_selected(self):
        """Handle playback run selection"""
        current_item = self.test_list.currentItem()

        if self._is_selectable_playback_item(current_item):
            selected_path = current_item.data(Qt.UserRole)
            playback_source = self._current_playback_source()
            if isinstance(selected_path, str) and playback_source == _PLAYBACK_SOURCE_REBUILD:
                self.selected_test = f"{_REBUILD_SELECTION_PREFIX}{selected_path}"
            else:
                self.selected_test = selected_path or current_item.text()
            self.selected_playback_source = playback_source
            self.playback_mode = True
            log.info(
                "Selected run for playback: %s (source=%s)",
                self.selected_test,
                playback_source,
            )
            self.accept()

    def _load_rebuild_status(self, run_dir: Path) -> dict[str, object]:
        try:
            return get_rebuild_artifact_status(run_dir, project_root=self._project_root())
        except Exception as exc:
            log.error("Failed to load rebuild status for %s: %s", run_dir, exc)
            return {
                "has_rebuild_artifacts": False,
                "status": "unknown",
                "summary_message": f"Failed to inspect rebuild artifacts: {exc}",
                "report_path": None,
                "available_streams": [],
            }

    def _current_playback_source(self) -> str:
        if hasattr(self, "playback_source_combo"):
            value = self.playback_source_combo.currentData()
            if isinstance(value, str) and value:
                return value
        return _PLAYBACK_SOURCE_NATIVE

    def _apply_rebuild_status(self, rebuild_status: dict[str, object]) -> None:
        if not hasattr(self, "playback_source_combo"):
            return

        self.playback_source_combo.blockSignals(True)
        self.playback_source_combo.clear()
        self.playback_source_combo.addItem("Native archive", _PLAYBACK_SOURCE_NATIVE)

        has_rebuild = bool(rebuild_status.get("has_rebuild_artifacts"))
        if has_rebuild:
            self.playback_source_combo.addItem("Rebuild artifacts", _PLAYBACK_SOURCE_REBUILD)
        self.playback_source_combo.setEnabled(True)
        self.playback_source_combo.blockSignals(False)

        self.prepare_rebuild_button.setEnabled(True)

        summary_message = str(rebuild_status.get("summary_message") or "")
        if has_rebuild:
            self.rebuild_status_label.setText(
                f"Rebuild artifacts available. {summary_message}".strip()
            )
            if self.playback_source_combo.findData(_PLAYBACK_SOURCE_REBUILD) >= 0:
                self.playback_source_combo.setCurrentIndex(0)
        else:
            self.rebuild_status_label.setText(
                summary_message or "Rebuild artifacts are not prepared for the selected run."
            )
            self.playback_source_combo.setCurrentIndex(0)

    def on_prepare_rebuild_clicked(self):
        current_item = (
            getattr(self, "test_list", None).currentItem()
            if hasattr(self, "test_list")
            else None
        )
        if current_item is None or not (current_item.flags() & Qt.ItemIsEnabled):
            QMessageBox.information(self, "Prepare Rebuild", "Select a playback run first.")
            return

        run_dir_str = current_item.data(Qt.UserRole)
        if not isinstance(run_dir_str, str):
            QMessageBox.warning(
                self,
                "Prepare Rebuild",
                "Selected playback item is missing a valid run path.",
            )
            return

        run_dir = Path(run_dir_str)
        self.prepare_rebuild_button.setEnabled(False)
        self.rebuild_status_label.setText("Preparing rebuild artifacts...")
        QApplication.processEvents()

        try:
            report = publish_run_rebuild_artifacts(run_dir, project_root=self._project_root())
        except Exception as exc:
            log.error("Failed to prepare rebuild for %s: %s", run_dir, exc)
            QMessageBox.critical(
                self,
                "Prepare Rebuild Failed",
                f"Failed to prepare rebuild artifacts.\n\nError: {exc}",
            )
            self.playback_rebuild_status_by_dir[run_dir_str] = {
                "has_rebuild_artifacts": False,
                "status": "failed",
                "summary_message": f"Failed to prepare rebuild artifacts: {exc}",
                "report_path": None,
                "available_streams": [],
            }
        else:
            self.playback_rebuild_status_by_dir[run_dir_str] = self._load_rebuild_status(run_dir)
            if report.get("status") == "published":
                QMessageBox.information(
                    self,
                    "Rebuild Ready",
                    str(report.get("summary_message") or "Rebuild artifacts published."),
                )
            else:
                QMessageBox.warning(
                    self,
                    "Rebuild Failed",
                    str(
                        report.get("summary_message")
                        or "Rebuild failed, please check data manually."
                    ),
                )
        finally:
            self.prepare_rebuild_button.setEnabled(True)

        rebuild_status = self.playback_rebuild_status_by_dir.get(run_dir_str, {})
        self._apply_rebuild_status(rebuild_status)
        if bool(rebuild_status.get("has_rebuild_artifacts")):
            rebuild_index = self.playback_source_combo.findData(_PLAYBACK_SOURCE_REBUILD)
            if rebuild_index >= 0:
                self.playback_source_combo.setCurrentIndex(rebuild_index)

    def _append_rebuild_detail_lines(
        self,
        lines: list[str],
        rebuild_status: dict[str, object],
    ) -> None:
        status = str(rebuild_status.get("status") or "unknown")
        summary_message = str(
            rebuild_status.get("summary_message") or "Rebuild artifacts unavailable."
        )
        lines.append("")
        lines.append(f"Rebuild status: {status}")
        lines.append(f"Rebuild summary: {summary_message}")

        report_path = rebuild_status.get("report_path")
        if isinstance(report_path, str) and report_path:
            lines.append(f"Rebuild report: {report_path}")

        available_streams = rebuild_status.get("available_streams")
        if isinstance(available_streams, list) and available_streams:
            lines.append(f"Rebuild streams: {', '.join(str(item) for item in available_streams)}")

    def set_bus_status(self, success, message=""):
        """Update bus initialization status"""
        if success:
            self.check_bus.set_pass(message or "Connected")
        else:
            self.check_bus.set_fail(message or "Failed to initialize")
            self._handle_failure("CAN bus initialization failed")

    def set_device_status(self, success, message=""):
        """Update device communication status"""
        if success:
            self.check_devices.set_pass(message or "All devices responding")
        else:
            self.check_devices.set_fail(message or "Some devices not responding")
            self.status_message.setText("Warning: " + message)
            self.status_message.setStyleSheet("color: #FFA726; margin: 10px; padding: 10px;")