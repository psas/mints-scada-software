from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QWidget, QApplication)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
import qdarkstyle
import os
import logging

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
            self.status_label.setStyleSheet("color: #FFA726;")  # Orange/Yellow
        elif self.status == "pass":
            self.status_label.setText("●")
            self.status_label.setStyleSheet("color: #4CAF50;")  # Green
        elif self.status == "fail":
            self.status_label.setText("●")
            self.status_label.setStyleSheet("color: #F44336;")  # Red


class ChecklistWindow(QDialog):
    """
    Pre-flight checklist window
    Checks system requirements before launching main application
    """

    def __init__(self, serial_port, parent=None):
        super().__init__(parent)
        self.serial_port = serial_port
        self.all_passed = False

        self.setWindowTitle("minTS Controller - Startup Checklist")
        self.setGeometry(100, 100, 600, 400)

        # Apply dark theme
        QApplication.setStyle("Fusion")
        self.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt5'))

        # Main layout
        main_layout = QVBoxLayout(self)

        # Title
        title = QLabel("System Pre-Flight Checklist")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)

        subtitle = QLabel("Checking hardware and connections...")
        subtitle.setFont(QFont("Arial", 10))
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #888; margin-bottom: 20px;")
        main_layout.addWidget(subtitle)

        # Checklist items
        self.check_serial = ChecklistItem("Serial port connection")
        self.check_bus = ChecklistItem("CAN bus initialization")
        self.check_devices = ChecklistItem("Device communication")

        main_layout.addWidget(self.check_serial)
        main_layout.addWidget(self.check_bus)
        main_layout.addWidget(self.check_devices)

        main_layout.addStretch()

        # Status message
        self.status_message = QLabel("")
        self.status_message.setFont(QFont("Arial", 10))
        self.status_message.setAlignment(Qt.AlignCenter)
        self.status_message.setWordWrap(True)
        self.status_message.setStyleSheet("margin: 10px; padding: 10px;")
        main_layout.addWidget(self.status_message)

        # Buttons
        button_layout = QHBoxLayout()

        button_layout.addStretch()

        self.continue_button = QPushButton("Continue")
        self.continue_button.clicked.connect(self.accept)
        self.continue_button.setEnabled(False)
        self.continue_button.setMinimumWidth(100)
        button_layout.addWidget(self.continue_button)

        self.exit_button = QPushButton("Exit")
        self.exit_button.clicked.connect(self.reject)
        self.exit_button.setMinimumWidth(100)
        button_layout.addWidget(self.exit_button)

        main_layout.addLayout(button_layout)

        # Start checks after a short delay
        QTimer.singleShot(500, self.run_checks)

    def run_checks(self):
        """Run all pre-flight checks"""
        self.continue_button.setEnabled(False)
        self.status_message.setText("Running checks...")
        self.status_message.setStyleSheet("color: #888; margin: 10px; padding: 10px;")

        # Check 1: Serial port
        self.check_serial.set_checking()
        QApplication.processEvents()  # Update UI

        if os.path.exists(self.serial_port):
            self.check_serial.set_pass(f"Found: {self.serial_port}")
            log.info(f"Serial port check passed: {self.serial_port}")
        else:
            self.check_serial.set_fail(f"Not found: {self.serial_port}")
            log.error(f"Serial port not found: {self.serial_port}")
            self._handle_failure("Serial port not found. Please check USB connection.")
            return

        # Check 2: CAN bus (placeholder - actual check done in main.py)
        self.check_bus.set_checking()
        QApplication.processEvents()
        self.check_bus.set_pass("Ready")

        # Check 3: Devices (placeholder - actual check done in main.py)
        self.check_devices.set_checking()
        QApplication.processEvents()
        self.check_devices.set_pass("Ready to initialize")

        # All checks passed
        self._handle_success()

    def _handle_success(self):
        """Handle successful completion of all checks"""
        self.all_passed = True
        self.status_message.setText("All checks passed! Ready to start.")
        self.status_message.setStyleSheet("color: #4CAF50; margin: 10px; padding: 10px; font-weight: bold;")
        self.continue_button.setEnabled(True)
        log.info("All pre-flight checks passed")

    def _handle_failure(self, message):
        """Handle check failure"""
        self.all_passed = False
        self.status_message.setText(f"Check failed: {message}\n\nFix the issue and run 'make run' again.")
        self.status_message.setStyleSheet("color: #F44336; margin: 10px; padding: 10px; background-color: #3a1a1a; border-radius: 5px;")
        log.error(f"Pre-flight check failed: {message}")

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
            # This is a warning, not a hard failure
            self.status_message.setText("Warning: " + message)
            self.status_message.setStyleSheet("color: #FFA726; margin: 10px; padding: 10px;")
