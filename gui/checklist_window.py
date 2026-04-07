from pathlib import Path
import json
import os
import socket
from datetime import datetime

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
    QFrame,
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
    "green": ("Ready", "#4CAF50", "#16301b"),
    "yellow": ("Check", "#FFC107", "#3a3211"),
    "red": ("Mismatch", "#F44336", "#3a1a1a"),
}

_INTEGRITY_ITEM_PREFIX: dict[str, str] = {
    "green": "[OK]",
    "yellow": "[CHECK]",
    "red": "[MISMATCH]",
}

_PLAYBACK_SOURCE_NATIVE = "native"
_PLAYBACK_SOURCE_REBUILD = "rebuild"
_REBUILD_SELECTION_PREFIX = "rebuild::"

_PRIMARY_BTN_STYLE = (
    "QPushButton { background-color: #2d7d46; color: white; border: 1px solid #4CAF50;"
    " border-radius: 6px; padding: 10px 22px; font-weight: bold; min-height: 34px; }"
    " QPushButton:hover { background-color: #388E3C; }"
    " QPushButton:pressed { background-color: #1B5E20; }"
    " QPushButton:disabled { background-color: #2a2a2a; color: #555;"
    " border: 1px solid #444; font-weight: normal; }"
)

_BTN_STYLE = (
    "QPushButton { padding: 9px 16px; min-height: 34px; border-radius: 6px; }"
)

_CARD_STYLE = (
    "QFrame {"
    " background-color: #1f1f1f;"
    " border: 1px solid #3b3b3b;"
    " border-radius: 10px;"
    "}"
)

_MUTED_LABEL_STYLE = "color: #9a9a9a;"
_SECTION_TITLE_STYLE = "color: #d9d9d9; font-weight: bold;"


class ChecklistItem(QWidget):
    """Individual checklist item with status indicator."""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(18, 10, 18, 10)
        self.layout.setSpacing(10)

        self.status_label = QLabel("○")
        self.status_label.setFont(QFont("Arial", 18))
        self.status_label.setFixedWidth(28)
        self.layout.addWidget(self.status_label)

        self.text_label = QLabel(text)
        self.text_label.setFont(QFont("Arial", 12, QFont.Bold))
        self.layout.addWidget(self.text_label)

        self.layout.addStretch()

        self.result_label = QLabel("")
        self.result_label.setFont(QFont("Arial", 10))
        self.result_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.result_label.setStyleSheet("color: #888;")
        self.layout.addWidget(self.result_label)

        self.status = "pending"  # pending, checking, pass, fail
        self._update_display()

    def set_checking(self):
        self.status = "checking"
        self._update_display()

    def set_pass(self, message=""):
        self.status = "pass"
        self.result_label.setText(message or "")
        self._update_display()

    def set_fail(self, message=""):
        self.status = "fail"
        self.result_label.setText(message or "")
        self._update_display()

    def _update_display(self):
        if self.status == "pending":
            self.status_label.setText("○")
            self.status_label.setStyleSheet("color: #555;")
            self.result_label.setStyleSheet("color: #777;")
        elif self.status == "checking":
            self.status_label.setText("◐")
            self.status_label.setStyleSheet("color: #FFA726;")
            self.result_label.setStyleSheet("color: #FFA726;")
        elif self.status == "pass":
            self.status_label.setText("●")
            self.status_label.setStyleSheet("color: #4CAF50;")
            self.result_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        elif self.status == "fail":
            self.status_label.setText("●")
            self.status_label.setStyleSheet("color: #F44336;")
            self.result_label.setStyleSheet("color: #F44336; font-weight: bold;")


class ChecklistWindow(QDialog):
    """
    Pre-flight checklist window.

    Supports two startup paths:
    - live mode: collect run metadata before backend/gateway startup
    - playback mode: select a recorded run from ignitionhistory

    Startup behavior:
    - System Startup only checks the serial link and shows lightweight status.
    - Live service startup and backend/gateway readiness are deferred to Live Setup
      / later live-launch stages.
    """

    def __init__(
        self,
        serial_port,
        parent=None,
        *,
        backend_socket_path: str | Path | None = None,
        auto_refresh_ms: int = 2000,
        live_startup_callback=None,
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
        self.live_startup_callback = live_startup_callback

        self.all_passed = False
        self.live_entry_allowed = False
        self.live_entry_mode = "blocked"  # blocked | full

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

        self.setWindowTitle("minTS Controller - Startup")
        self.resize(980, 720)
        self.setMinimumSize(900, 660)

        QApplication.setStyle("Fusion")
        self.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyqt5"))

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(26, 22, 26, 22)
        self.main_layout.setSpacing(14)

        self.checklist_widget = self._build_checklist_widget()
        self.main_layout.addWidget(self.checklist_widget)

        self._check_refresh_timer = QTimer(self)
        self._check_refresh_timer.setInterval(self._check_refresh_ms)
        self._check_refresh_timer.timeout.connect(self._maybe_refresh_checks)
        self._check_refresh_timer.start()

        QTimer.singleShot(400, self.run_checks)

    def _build_checklist_widget(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        title = QLabel("System Startup")
        title.setFont(QFont("Arial", 20, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Checking serial link and startup environment.")
        subtitle.setFont(QFont("Arial", 11))
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #9a9a9a; margin-bottom: 6px;")
        layout.addWidget(subtitle)

        checks_card = QFrame()
        checks_card.setStyleSheet(_CARD_STYLE)
        checks_layout = QVBoxLayout(checks_card)
        checks_layout.setContentsMargins(10, 10, 10, 10)
        checks_layout.setSpacing(2)

        self.check_serial = ChecklistItem("Serial link")
        self.check_bus = ChecklistItem("Live services")
        self.check_devices = ChecklistItem("Device readiness")

        checks_layout.addWidget(self.check_serial)
        checks_layout.addWidget(self.check_bus)
        checks_layout.addWidget(self.check_devices)

        layout.addWidget(checks_card)

        self.status_message = QLabel("")
        self.status_message.setFont(QFont("Arial", 11))
        self.status_message.setAlignment(Qt.AlignCenter)
        self.status_message.setWordWrap(True)
        self.status_message.setStyleSheet(
            "margin-top: 6px; padding: 12px; border-radius: 8px; color: #888;"
        )
        layout.addWidget(self.status_message)

        layout.addStretch()

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        self.playback_button = QPushButton("Playback")
        self.playback_button.clicked.connect(self.show_playback_selection)
        self.playback_button.setMinimumWidth(120)
        self.playback_button.setStyleSheet(_BTN_STYLE)
        button_layout.addWidget(self.playback_button)

        button_layout.addStretch()

        self.continue_button = QPushButton("Live")
        self.continue_button.clicked.connect(self.show_live_setup)
        self.continue_button.setEnabled(False)
        self.continue_button.setMinimumWidth(130)
        self.continue_button.setStyleSheet(_PRIMARY_BTN_STYLE)
        button_layout.addWidget(self.continue_button)

        self.exit_button = QPushButton("Exit")
        self.exit_button.clicked.connect(self.reject)
        self.exit_button.setMinimumWidth(110)
        self.exit_button.setStyleSheet(_BTN_STYLE)
        button_layout.addWidget(self.exit_button)

        layout.addLayout(button_layout)
        return widget

    def _build_live_setup_widget(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        title = QLabel("Live Run Setup")
        title.setFont(QFont("Arial", 20, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Enter the basic info for this live session.")
        subtitle.setFont(QFont("Arial", 11))
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #9a9a9a; margin-bottom: 6px;")
        layout.addWidget(subtitle)

        form_card = QFrame()
        form_card.setStyleSheet(_CARD_STYLE)
        form_layout_outer = QVBoxLayout(form_card)
        form_layout_outer.setContentsMargins(24, 20, 24, 20)

        form_layout = QFormLayout()
        form_layout.setSpacing(14)
        form_layout.setLabelAlignment(Qt.AlignRight)

        self.test_name_input = QLineEdit()
        self.test_name_input.setPlaceholderText("Example: ignition_test_01")
        form_layout.addRow("Test name *", self.test_name_input)

        self.operator_input = QLineEdit()
        self.operator_input.setPlaceholderText("Operator name")
        form_layout.addRow("Operator *", self.operator_input)

        self.profile_input = QLineEdit()
        self.profile_input.setPlaceholderText("Optional")
        form_layout.addRow("Profile", self.profile_input)

        self.notes_input = QPlainTextEdit()
        self.notes_input.setPlaceholderText("Optional")
        self.notes_input.setMinimumHeight(110)
        form_layout.addRow("Notes", self.notes_input)

        form_layout_outer.addLayout(form_layout)
        layout.addWidget(form_card)

        req_note = QLabel("* Required")
        req_note.setFont(QFont("Arial", 10))
        req_note.setStyleSheet("color: #888; margin-left: 10px;")
        layout.addWidget(req_note)

        self.live_setup_status = QLabel(
            "Enter test name and operator to continue."
        )
        self.live_setup_status.setWordWrap(True)
        self.live_setup_status.setAlignment(Qt.AlignCenter)
        self.live_setup_status.setStyleSheet(
            "color: #888; margin-top: 4px; padding: 10px;"
        )
        layout.addWidget(self.live_setup_status)

        layout.addStretch()

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        back_button = QPushButton("Back")
        back_button.clicked.connect(self.show_checklist)
        back_button.setMinimumWidth(110)
        back_button.setStyleSheet(_BTN_STYLE)
        button_layout.addWidget(back_button)

        button_layout.addStretch()

        self.live_continue_button = QPushButton("Continue")
        self.live_continue_button.clicked.connect(self.on_live_selected)
        self.live_continue_button.setEnabled(False)
        self.live_continue_button.setMinimumWidth(130)
        self.live_continue_button.setStyleSheet(_PRIMARY_BTN_STYLE)
        button_layout.addWidget(self.live_continue_button)

        exit_button = QPushButton("Exit")
        exit_button.clicked.connect(self.reject)
        exit_button.setMinimumWidth(110)
        exit_button.setStyleSheet(_BTN_STYLE)
        button_layout.addWidget(exit_button)

        layout.addLayout(button_layout)

        self.test_name_input.textChanged.connect(self._update_live_continue_state)
        self.operator_input.textChanged.connect(self._update_live_continue_state)
        self.test_name_input.returnPressed.connect(self._maybe_submit_live_setup)
        self.operator_input.returnPressed.connect(self._maybe_submit_live_setup)
        self.profile_input.returnPressed.connect(self._maybe_submit_live_setup)

        return widget

    def run_checks(self):
        """Run lightweight startup checks for launcher entry."""
        self.continue_button.setEnabled(False)
        self.live_entry_allowed = False
        self.live_entry_mode = "blocked"
        self.all_passed = False
        self.backend_probe_snapshot = None

        self.status_message.setText("Running startup checks...")
        self.status_message.setStyleSheet(
            "color: #888; padding: 12px; border-radius: 8px;"
        )

        self.check_serial.set_checking()
        QApplication.processEvents()

        serial_ok = Path(self.serial_port).exists()
        if serial_ok:
            self.check_serial.set_pass("Connected")
            log.info("Serial port check passed: %s", self.serial_port)
        else:
            self.check_serial.set_fail("Not detected")
            log.error("Serial port not found: %s", self.serial_port)

        # These are intentionally deferred to the later Live Setup / launch flow.
        self.check_bus.set_pass("Deferred to Live Setup")
        self.check_devices.set_pass("Deferred to Live Setup")

        if serial_ok:
            self._handle_success()
        else:
            self._handle_failure("serial link missing")

    def _handle_success(self):
        self.all_passed = True
        self.live_entry_allowed = True
        self.live_entry_mode = "full"
        self.status_message.setText(
            "Serial link detected. Continue to Live Setup."
        )
        self.status_message.setStyleSheet(
            "color: #4CAF50; padding: 12px; border-radius: 8px; font-weight: bold;"
        )
        self.continue_button.setEnabled(True)
        log.info("Startup serial check passed; live entry is allowed")

    def _handle_failure(self, message):
        self.all_passed = False
        self.live_entry_allowed = False
        self.live_entry_mode = "blocked"
        self.status_message.setText(
            "Live mode is blocked right now.\nPlayback is still available."
        )
        self.status_message.setStyleSheet(
            "color: #F44336; padding: 12px; "
            "background-color: #3a1a1a; border-radius: 8px;"
        )
        log.error("Startup check failed: %s", message)

    def show_live_setup(self):
        """Switch to live run metadata entry view."""
        self.run_checks()

        if not self.live_entry_allowed:
            QMessageBox.warning(
                self,
                "Live Mode Not Ready",
                "Live mode requires a detected serial link before continuing.",
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
        """Switch to playback run selection view."""
        self.checklist_widget.hide()
        if hasattr(self, "live_setup_widget"):
            self.live_setup_widget.hide()

        if hasattr(self, "playback_widget"):
            self.playback_widget.hide()
            self.main_layout.removeWidget(self.playback_widget)
            self.playback_widget.deleteLater()
            del self.playback_widget

        self.playback_widget = QWidget()
        playback_layout = QVBoxLayout(self.playback_widget)
        playback_layout.setContentsMargins(0, 0, 0, 0)
        playback_layout.setSpacing(14)

        title = QLabel("Playback")
        title.setFont(QFont("Arial", 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        playback_layout.addWidget(title)

        subtitle = QLabel(
            f"Choose a recorded run from {HISTORY_ROOT_DIRNAME} and continue."
        )
        subtitle.setFont(QFont("Arial", 10))
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #9a9a9a; margin-bottom: 8px;")
        playback_layout.addWidget(subtitle)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(14)

        # Left side: run list
        list_card = QFrame()
        list_card.setStyleSheet(
            "QFrame { background-color: #1f1f1f; border: 1px solid #3b3b3b; border-radius: 10px; }"
        )
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(14, 14, 14, 14)
        list_layout.setSpacing(10)

        runs_label = QLabel("Available runs")
        runs_label.setFont(QFont("Arial", 12, QFont.Bold))
        runs_label.setStyleSheet("color: #e5e5e5;")
        list_layout.addWidget(runs_label)

        self.test_list = QListWidget()
        self.test_list.setFont(QFont("Arial", 11))
        self.test_list.setSelectionMode(QListWidget.SingleSelection)
        self.test_list.currentItemChanged.connect(self.on_playback_item_changed)
        self.test_list.setMinimumWidth(420)
        self.test_list.setMinimumHeight(340)
        list_layout.addWidget(self.test_list, 1)

        content_layout.addWidget(list_card, 3)

        # Right side: simplified summary
        summary_card = QFrame()
        summary_card.setStyleSheet(
            "QFrame { background-color: #1f1f1f; border: 1px solid #3b3b3b; border-radius: 10px; }"
        )
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(16, 16, 16, 16)
        summary_layout.setSpacing(10)

        selected_label = QLabel("Selected run")
        selected_label.setFont(QFont("Arial", 12, QFont.Bold))
        selected_label.setStyleSheet("color: #e5e5e5;")
        summary_layout.addWidget(selected_label)

        self.playback_selected_title = QLabel("No run selected")
        self.playback_selected_title.setFont(QFont("Arial", 15, QFont.Bold))
        self.playback_selected_title.setWordWrap(True)
        self.playback_selected_title.setStyleSheet("color: #f1f1f1;")
        summary_layout.addWidget(self.playback_selected_title)

        self.playback_selected_subtitle = QLabel("")
        self.playback_selected_subtitle.setFont(QFont("Arial", 10))
        self.playback_selected_subtitle.setWordWrap(True)
        self.playback_selected_subtitle.setStyleSheet("color: #9a9a9a;")
        summary_layout.addWidget(self.playback_selected_subtitle)

        self.integrity_badge_label = QLabel("Select a run to see its status.")
        self.integrity_badge_label.setAlignment(Qt.AlignCenter)
        self.integrity_badge_label.setWordWrap(True)
        self.integrity_badge_label.setMinimumHeight(54)
        self.integrity_badge_label.setStyleSheet(
            "padding: 10px; border-radius: 8px; color: #ddd; background-color: #252525;"
        )
        summary_layout.addWidget(self.integrity_badge_label)

        self.playback_summary_label = QLabel("Pick a run from the left.")
        self.playback_summary_label.setWordWrap(True)
        self.playback_summary_label.setStyleSheet("color: #d0d0d0;")
        summary_layout.addWidget(self.playback_summary_label)

        source_row = QHBoxLayout()
        source_row.setSpacing(8)

        source_label = QLabel("Source")
        source_label.setStyleSheet("color: #9a9a9a;")
        source_row.addWidget(source_label)

        self.playback_source_combo = QComboBox()
        self.playback_source_combo.addItem("Native archive", _PLAYBACK_SOURCE_NATIVE)
        self.playback_source_combo.setEnabled(False)
        self.playback_source_combo.currentIndexChanged.connect(
            self._refresh_selected_playback_summary
        )
        source_row.addWidget(self.playback_source_combo, 1)

        summary_layout.addLayout(source_row)

        self.prepare_rebuild_button = QPushButton("Prepare Rebuild")
        self.prepare_rebuild_button.setEnabled(False)
        self.prepare_rebuild_button.clicked.connect(self.on_prepare_rebuild_clicked)
        self.prepare_rebuild_button.setStyleSheet(
            "QPushButton { padding: 7px 12px; min-height: 28px; border-radius: 6px; }"
        )
        summary_layout.addWidget(self.prepare_rebuild_button)

        summary_layout.addStretch()
        content_layout.addWidget(summary_card, 2)

        playback_layout.addLayout(content_layout, 1)

        self._load_available_tests()

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        back_button = QPushButton("Back")
        back_button.clicked.connect(self.show_checklist)
        back_button.setMinimumWidth(110)
        back_button.setStyleSheet(_BTN_STYLE)
        button_layout.addWidget(back_button)

        button_layout.addStretch()

        self.playback_continue_button = QPushButton("Continue")
        self.playback_continue_button.clicked.connect(self.on_test_selected)
        self.playback_continue_button.setEnabled(False)
        self.playback_continue_button.setMinimumWidth(130)
        self.playback_continue_button.setStyleSheet(_PRIMARY_BTN_STYLE)
        button_layout.addWidget(self.playback_continue_button)

        exit_button = QPushButton("Exit")
        exit_button.clicked.connect(self.reject)
        exit_button.setMinimumWidth(110)
        exit_button.setStyleSheet(_BTN_STYLE)
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

    def _format_wall_time_compact(self, value: str | None) -> str:
        if not value:
            return ""
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return value.strip()

    def _playback_primary_name(self, summary: PlaybackRunSummary | None) -> str:
        if summary is None:
            return "No run selected"
        test_name = (summary.test_name or "").strip()
        return test_name or summary.run_id

    def _playback_secondary_line(self, summary: PlaybackRunSummary | None) -> str:
        if summary is None:
            return ""
        parts: list[str] = []
        operator = (summary.operator or "").strip()
        time_text = self._format_wall_time_compact(summary.start_wall_time)

        if operator:
            parts.append(operator)
        if time_text:
            parts.append(time_text)

        return " | ".join(parts)

    def _playback_badge_text(self, badge: str, report: dict | None = None) -> str:
        if badge == "green":
            return "Ready for playback"
        if badge == "yellow":
            summary_msg = ""
            if isinstance(report, dict):
                summary_msg = str(report.get("summary_message") or "").strip()
            return f"Check archive: {summary_msg}" if summary_msg else "Check archive"

        # Red badge — identify which streams have issues.
        if isinstance(report, dict):
            stream_reports = report.get("stream_reports")
            if isinstance(stream_reports, dict):
                bad_streams = sorted(
                    name for name, sr in stream_reports.items()
                    if isinstance(sr, dict) and sr.get("status") in ("mismatch", "missing")
                )
                if bad_streams:
                    return f"Archive mismatch: {', '.join(bad_streams)}"
            summary_msg = str(report.get("summary_message") or "").strip()
            if summary_msg:
                return f"Archive mismatch: {summary_msg}"
        return "Archive mismatch"

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
                "Live metadata is ready. Continue to launch live services and start the session."
            )
            self.live_setup_status.setStyleSheet(
                "color: #4CAF50; padding: 10px;"
            )
        else:
            self.live_setup_status.setText(
                "Enter test name and operator to continue."
            )
            self.live_setup_status.setStyleSheet(
                "color: #888; padding: 10px;"
            )

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
                "color: #F44336; padding: 10px;"
                "background-color: #3a1a1a; border-radius: 8px;"
            )
            self.test_name_input.setFocus()
            return

        if not operator:
            self.live_setup_status.setText("Operator is required.")
            self.live_setup_status.setStyleSheet(
                "color: #F44336; padding: 10px;"
                "background-color: #3a1a1a; border-radius: 8px;"
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

        if callable(self.live_startup_callback):
            self._live_init_in_progress = True
            if self.live_continue_button is not None:
                self.live_continue_button.setEnabled(False)
            self.live_setup_status.setText("Starting live services...")
            self.live_setup_status.setStyleSheet(
                "color: #FFA726; padding: 10px; background-color: #3a3211; border-radius: 8px;"
            )
            QApplication.processEvents()

            try:
                ok, message = self.live_startup_callback(dict(self.live_run_metadata))
            except Exception as exc:
                ok = False
                message = f"Failed to start live services: {exc}"
            finally:
                self._live_init_in_progress = False

            if not ok:
                self.live_setup_status.setText(message or "Failed to start live services.")
                self.live_setup_status.setStyleSheet(
                    "color: #F44336; padding: 10px; background-color: #3a1a1a; border-radius: 8px;"
                )
                if self.live_continue_button is not None:
                    self.live_continue_button.setEnabled(True)
                return

            self.live_setup_status.setText(message or "Live services are ready.")
            self.live_setup_status.setStyleSheet(
                "color: #4CAF50; padding: 10px; background-color: #16301b; border-radius: 8px;"
            )
            QApplication.processEvents()

        self.playback_mode = False
        log.info(
            "Selected live startup metadata: %s (entry_mode=%s)",
            self.live_run_metadata,
            self.live_entry_mode,
        )
        self.accept()

    def _ignitionhistory_path(self) -> Path:
        return self._project_root() / HISTORY_ROOT_DIRNAME

    def _load_available_tests(self):
        """Load available playback runs from ignitionhistory folder."""
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

                primary = self._playback_primary_name(summary)
                secondary = self._playback_secondary_line(summary)

                item_text = f"{prefix} {primary}"
                if secondary:
                    item_text += f"\n{secondary}"

                item = QListWidgetItem(item_text)
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
        self._refresh_selected_playback_summary()

        if current is None or not (current.flags() & Qt.ItemIsEnabled):
            return

        run_dir_str = current.data(Qt.UserRole)
        rebuild_status = {}
        if isinstance(run_dir_str, str):
            rebuild_status = self.playback_rebuild_status_by_dir.get(run_dir_str, {})
        self._apply_rebuild_status(rebuild_status if isinstance(rebuild_status, dict) else {})

    def _refresh_selected_playback_summary(self) -> None:
        current = self.test_list.currentItem() if hasattr(self, "test_list") else None
        if current is None or not self._is_selectable_playback_item(current):
            self._set_integrity_placeholder("Select a run to view its summary.")
            return

        run_dir_str = current.data(Qt.UserRole)
        report = current.data(Qt.UserRole + 1)

        if not isinstance(run_dir_str, str):
            self._set_integrity_placeholder("Selected run is missing its path.")
            return

        if not isinstance(report, dict):
            report = self.playback_integrity_reports.get(run_dir_str)

        summary = self.playback_run_summaries_by_dir.get(run_dir_str)
        rebuild_status = self.playback_rebuild_status_by_dir.get(run_dir_str, {})

        if not isinstance(report, dict):
            self._set_integrity_placeholder("Integrity summary is unavailable for this run.")
            return

        self._apply_integrity_report(
            report,
            summary if isinstance(summary, PlaybackRunSummary) else None,
            rebuild_status if isinstance(rebuild_status, dict) else {},
        )

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

    def _apply_integrity_report(
        self,
        report: dict[str, object],
        summary: PlaybackRunSummary | None,
        rebuild_status: dict[str, object],
    ) -> None:
        if hasattr(self, "playback_selected_title"):
            self.playback_selected_title.setText(
                self._playback_primary_name(summary)
            )

        if hasattr(self, "playback_selected_subtitle"):
            self.playback_selected_subtitle.setText(
                self._playback_secondary_line(summary)
            )

        badge = str(report.get("badge") or "red")
        badge_text = self._playback_badge_text(badge, report)

        if badge == "green":
            fg, bg = "#4CAF50", "#16301b"
        elif badge == "yellow":
            fg, bg = "#FFC107", "#3a3211"
        else:
            fg, bg = "#F44336", "#3a1a1a"

        self.integrity_badge_label.setText(badge_text)
        self.integrity_badge_label.setStyleSheet(
            f"padding: 10px; border-radius: 8px; color: {fg}; "
            f"background-color: {bg}; font-weight: bold;"
        )

        self.playback_summary_label.setText(
            self._build_playback_summary_text(rebuild_status)
        )

    def _build_playback_summary_text(
        self,
        rebuild_status: dict[str, object] | None = None,
    ) -> str:
        selected_source = self._current_playback_source()

        if isinstance(rebuild_status, dict) and bool(rebuild_status.get("has_rebuild_artifacts")):
            if selected_source == _PLAYBACK_SOURCE_REBUILD:
                return "Using rebuild artifacts."
            return "Using native archive. Rebuild is also available."

        return "Using native archive."

    def _set_integrity_placeholder(self, text: str) -> None:
        if hasattr(self, "playback_selected_title"):
            self.playback_selected_title.setText("No run selected")
        if hasattr(self, "playback_selected_subtitle"):
            self.playback_selected_subtitle.setText("")
        if hasattr(self, "integrity_badge_label"):
            self.integrity_badge_label.setText(text)
            self.integrity_badge_label.setStyleSheet(
                "padding: 10px; border-radius: 8px; color: #ddd; background-color: #252525;"
            )
        if hasattr(self, "playback_summary_label"):
            self.playback_summary_label.setText("Pick a run from the left.")
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

    def _build_list_item_tooltip(self, base_tooltip: str, report: dict[str, object]) -> str:
        parts = [base_tooltip]
        summary_message = report.get("summary_message")
        if isinstance(summary_message, str) and summary_message.strip():
            parts.extend(["", f"Integrity: {summary_message.strip()}"])
        return "\n".join(parts)

    def _integrity_qcolor(self, badge: str) -> QColor:
        if badge == "green":
            return QColor("#4CAF50")
        if badge == "yellow":
            return QColor("#FFC107")
        return QColor("#F44336")

    def on_test_selected(self):
        """Handle playback run selection."""
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

        self.playback_source_combo.setEnabled(self.playback_source_combo.count() > 1)
        self.playback_source_combo.blockSignals(False)

        self.prepare_rebuild_button.setEnabled(True)

        if has_rebuild:
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
        self.playback_summary_label.setText("Preparing rebuild artifacts...")
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

        self._refresh_selected_playback_summary()

    def set_bus_status(self, success, message=""):
        """Update bus initialization status."""
        if success:
            self.check_bus.set_pass(message or "Ready")
        else:
            self.check_bus.set_fail(message or "Not ready")
            self._handle_failure("live bus unavailable")

    def set_device_status(self, success, message=""):
        """Update device communication status."""
        if success:
            self.check_devices.set_pass(message or "Ready")
        else:
            self.check_devices.set_fail(message or "Unavailable")
            self.status_message.setText("Some devices are not fully ready.")
            self.status_message.setStyleSheet(
                "color: #FFA726; padding: 12px; background-color: #3a3211; border-radius: 8px;"
            )