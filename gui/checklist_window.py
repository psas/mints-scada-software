from pathlib import Path
from gui.playback_catalog import discover_playback_runs

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
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
import qdarkstyle
import logging

from historymanager.paths import HISTORY_ROOT_DIRNAME

"""
Startup Checklist Window
Performs pre-flight checks before launching main application
"""

log = logging.getLogger("checklist")


class ChecklistItem(QWidget):
    """Individual checklist item with status indicator"""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(10, 5, 10, 5)

        # Status indicator (LED-style)
        self.status_label = QLabel("○")
        self.status_label.setFont(QFont("Arial", 16))
        self.status_label.setFixedWidth(30)
        self.layout.addWidget(self.status_label)

        # Description
        self.text_label = QLabel(text)
        self.text_label.setFont(QFont("Arial", 11))
        self.layout.addWidget(self.text_label)

        # Result message
        self.result_label = QLabel("")
        self.result_label.setFont(QFont("Arial", 9))
        self.result_label.setStyleSheet("color: #888;")
        self.layout.addWidget(self.result_label)

        self.layout.addStretch()

        self.status = "pending"  # pending, checking, pass, fail
        self._update_display()

    def set_checking(self):
        """Mark item as currently being checked"""
        self.status = "checking"
        self._update_display()

    def set_pass(self, message=""):
        """Mark item as passed"""
        self.status = "pass"
        if message:
            self.result_label.setText(message)
        self._update_display()

    def set_fail(self, message=""):
        """Mark item as failed"""
        self.status = "fail"
        if message:
            self.result_label.setText(message)
        self._update_display()

    def _update_display(self):
        """Update visual display based on status"""
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

    def __init__(self, serial_port, parent=None):
        super().__init__(parent)
        self.serial_port = serial_port
        self.all_passed = False
        self.selected_test = None
        self.playback_mode = False
        self.live_run_metadata: dict[str, str] | None = None

        self.setWindowTitle("minTS Controller - Startup Checklist")
        self.setGeometry(100, 100, 640, 460)

        QApplication.setStyle("Fusion")
        self.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyqt5"))

        self.main_layout = QVBoxLayout(self)

        self.checklist_widget = self._build_checklist_widget()
        self.main_layout.addWidget(self.checklist_widget)

        QTimer.singleShot(500, self.run_checks)

    def _build_checklist_widget(self) -> QWidget:
        widget = QWidget()
        checklist_layout = QVBoxLayout(widget)
        checklist_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("System Pre-Flight Checklist")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        checklist_layout.addWidget(title)

        subtitle = QLabel("Checking hardware and connections...")
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

        subtitle = QLabel("Enter run metadata before backend start_run.")
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

        self.live_setup_status = QLabel("")
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

        start_button = QPushButton("Start Live")
        start_button.clicked.connect(self.on_live_selected)
        start_button.setMinimumWidth(120)
        button_layout.addWidget(start_button)

        exit_button = QPushButton("Exit")
        exit_button.clicked.connect(self.reject)
        exit_button.setMinimumWidth(100)
        button_layout.addWidget(exit_button)

        layout.addLayout(button_layout)
        return widget

    def run_checks(self):
        """Run all pre-flight checks"""
        self.continue_button.setEnabled(False)
        self.status_message.setText("Running checks...")
        self.status_message.setStyleSheet("color: #888; margin: 10px; padding: 10px;")

        self.check_serial.set_checking()
        QApplication.processEvents()

        if Path(self.serial_port).exists():
            self.check_serial.set_pass(f"Found: {self.serial_port}")
            log.info("Serial port check passed: %s", self.serial_port)
        else:
            self.check_serial.set_fail(f"Not found: {self.serial_port}")
            log.error("Serial port not found: %s", self.serial_port)
            self._handle_failure("Serial port not found. Please check USB connection.")
            return

        self.check_bus.set_checking()
        QApplication.processEvents()
        self.check_bus.set_pass("Ready")

        self.check_devices.set_checking()
        QApplication.processEvents()
        self.check_devices.set_pass("Ready to initialize")

        self._handle_success()

    def _handle_success(self):
        """Handle successful completion of all checks"""
        self.all_passed = True
        self.status_message.setText("All checks passed! Ready to continue.")
        self.status_message.setStyleSheet(
            "color: #4CAF50; margin: 10px; padding: 10px; font-weight: bold;"
        )
        self.continue_button.setEnabled(True)
        log.info("All pre-flight checks passed")

    def _handle_failure(self, message):
        """Handle check failure"""
        self.all_passed = False
        self.status_message.setText(
            f"Check failed: {message}\n\nFix the issue and run 'make run' again."
        )
        self.status_message.setStyleSheet(
            "color: #F44336; margin: 10px; padding: 10px; "
            "background-color: #3a1a1a; border-radius: 5px;"
        )
        log.error("Pre-flight check failed: %s", message)

    def show_live_setup(self):
        """Switch to live run metadata entry view."""
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

        subtitle = QLabel(f"Choose a run from {HISTORY_ROOT_DIRNAME}")
        subtitle.setFont(QFont("Arial", 10))
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #888; margin-bottom: 20px;")
        playback_layout.addWidget(subtitle)

        self.test_list = QListWidget()
        self.test_list.setFont(QFont("Arial", 11))
        self.test_list.itemDoubleClicked.connect(self.on_test_selected)
        playback_layout.addWidget(self.test_list)

        self._load_available_tests()

        button_layout = QHBoxLayout()

        back_button = QPushButton("Back")
        back_button.clicked.connect(self.show_checklist)
        back_button.setMinimumWidth(100)
        button_layout.addWidget(back_button)

        button_layout.addStretch()

        select_button = QPushButton("Select")
        select_button.clicked.connect(self.on_test_selected)
        select_button.setMinimumWidth(100)
        button_layout.addWidget(select_button)

        exit_button = QPushButton("Exit")
        exit_button.clicked.connect(self.reject)
        exit_button.setMinimumWidth(100)
        button_layout.addWidget(exit_button)

        playback_layout.addLayout(button_layout)

        self.main_layout.addWidget(self.playback_widget)
        self.playback_widget.show()

    def show_checklist(self):
        """Switch back to the main checklist view."""
        if hasattr(self, "playback_widget"):
            self.playback_widget.hide()
            self.main_layout.removeWidget(self.playback_widget)
            self.playback_widget.deleteLater()
            del self.playback_widget

        if hasattr(self, "live_setup_widget"):
            self.live_setup_widget.hide()

        self.checklist_widget.show()

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

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def _ignitionhistory_path(self) -> Path:
        return self._project_root() / HISTORY_ROOT_DIRNAME

    def _load_available_tests(self):
        """Load available playback runs from ignitionhistory folder"""
        self.test_list.clear()
        history_path = self._ignitionhistory_path()

        if not history_path.exists():
            item = QListWidgetItem("No playback runs available")
            item.setFlags(Qt.NoItemFlags)
            self.test_list.addItem(item)
            log.info("%s folder does not exist", history_path)
            return

        try:
            run_summaries = discover_playback_runs(self._project_root())

            if not run_summaries:
                item = QListWidgetItem("No playback runs available")
                item.setFlags(Qt.NoItemFlags)
                self.test_list.addItem(item)
                log.info("No run directories with metadata.json found in %s", history_path)
                return

            for summary in run_summaries:
                item = QListWidgetItem(
                    f"{summary.display_title}\n{summary.display_subtitle}"
                )
                item.setData(Qt.UserRole, str(summary.run_dir))
                item.setToolTip(summary.tooltip_text)
                self.test_list.addItem(item)

            log.info("Found %d playback runs in %s", len(run_summaries), history_path)

        except Exception as e:
            log.error("Error loading playback runs: %s", e)
            item = QListWidgetItem(f"Error loading playback runs: {e}")
            item.setFlags(Qt.NoItemFlags)
            self.test_list.addItem(item)

    def on_test_selected(self):
        """Handle playback run selection"""
        current_item = self.test_list.currentItem()

        if current_item and current_item.flags() & Qt.ItemIsEnabled:
            selected_path = current_item.data(Qt.UserRole)
            self.selected_test = selected_path or current_item.text()
            self.playback_mode = True
            log.info("Selected run for playback: %s", self.selected_test)
            self.accept()

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
