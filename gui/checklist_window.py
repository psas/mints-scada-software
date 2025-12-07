from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QWidget, QApplication, QListWidget,
                              QListWidgetItem)
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
        self.selected_test = None  # Will store selected test folder name
        self.playback_mode = False  # Track if user selected playback

        self.setWindowTitle("minTS Controller - Startup Checklist")
        self.setGeometry(100, 100, 600, 400)

        # Apply dark theme
        QApplication.setStyle("Fusion")
        self.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt5'))

        # Main layout
        self.main_layout = QVBoxLayout(self)

        # Create checklist content widget
        self.checklist_widget = QWidget()
        checklist_layout = QVBoxLayout(self.checklist_widget)
        checklist_layout.setContentsMargins(0, 0, 0, 0)

        # Title
        title = QLabel("System Pre-Flight Checklist")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        checklist_layout.addWidget(title)

        subtitle = QLabel("Checking hardware and connections...")
        subtitle.setFont(QFont("Arial", 10))
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #888; margin-bottom: 20px;")
        checklist_layout.addWidget(subtitle)

        # Checklist items
        self.check_serial = ChecklistItem("Serial port connection")
        self.check_bus = ChecklistItem("CAN bus initialization")
        self.check_devices = ChecklistItem("Device communication")

        checklist_layout.addWidget(self.check_serial)
        checklist_layout.addWidget(self.check_bus)
        checklist_layout.addWidget(self.check_devices)

        checklist_layout.addStretch()

        # Status message
        self.status_message = QLabel("")
        self.status_message.setFont(QFont("Arial", 10))
        self.status_message.setAlignment(Qt.AlignCenter)
        self.status_message.setWordWrap(True)
        self.status_message.setStyleSheet("margin: 10px; padding: 10px;")
        checklist_layout.addWidget(self.status_message)

        # Buttons
        button_layout = QHBoxLayout()

        self.playback_button = QPushButton("Playback")
        self.playback_button.clicked.connect(self.show_playback_selection)
        self.playback_button.setMinimumWidth(100)
        button_layout.addWidget(self.playback_button)

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

        checklist_layout.addLayout(button_layout)

        # Add checklist widget to main layout
        self.main_layout.addWidget(self.checklist_widget)

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

    def show_playback_selection(self):
        """Switch to playback test selection view"""
        # Hide checklist widget
        self.checklist_widget.hide()

        # Create playback selection widget
        self.playback_widget = QWidget()
        playback_layout = QVBoxLayout(self.playback_widget)
        playback_layout.setContentsMargins(0, 0, 0, 0)

        # Title
        title = QLabel("Select Test to Playback")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        playback_layout.addWidget(title)

        subtitle = QLabel("Choose a test from the list below")
        subtitle.setFont(QFont("Arial", 10))
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #888; margin-bottom: 20px;")
        playback_layout.addWidget(subtitle)

        # List of available tests
        self.test_list = QListWidget()
        self.test_list.setFont(QFont("Arial", 11))
        self.test_list.itemDoubleClicked.connect(self.on_test_selected)
        playback_layout.addWidget(self.test_list)

        # Load tests from testhistory folder
        self._load_available_tests()

        # Buttons
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

        # Add playback widget to main layout
        self.main_layout.addWidget(self.playback_widget)

    def show_checklist(self):
        """Switch back to checklist view"""
        if hasattr(self, 'playback_widget'):
            self.playback_widget.hide()
            self.main_layout.removeWidget(self.playback_widget)
            self.playback_widget.deleteLater()
        self.checklist_widget.show()

    def _load_available_tests(self):
        """Load available tests from testhistory folder"""
        self.test_list.clear()
        testhistory_path = os.path.join(os.getcwd(), "testhistory")

        # Check if testhistory folder exists
        if not os.path.exists(testhistory_path):
            # Show "no tests available" message
            item = QListWidgetItem("No tests available")
            item.setFlags(Qt.NoItemFlags)  # Make it non-selectable
            self.test_list.addItem(item)
            log.info("testhistory folder does not exist")
            return

        # List all subdirectories in testhistory
        try:
            subdirs = [d for d in os.listdir(testhistory_path)
                      if os.path.isdir(os.path.join(testhistory_path, d))]

            if not subdirs:
                # No tests found
                item = QListWidgetItem("No tests available")
                item.setFlags(Qt.NoItemFlags)  # Make it non-selectable
                self.test_list.addItem(item)
                log.info("No test subdirectories found in testhistory")
            else:
                # Sort by name (which should be dates)
                subdirs.sort(reverse=True)  # Most recent first
                for subdir in subdirs:
                    self.test_list.addItem(subdir)
                log.info(f"Found {len(subdirs)} tests in testhistory")
        except Exception as e:
            log.error(f"Error loading tests: {e}")
            item = QListWidgetItem(f"Error loading tests: {e}")
            item.setFlags(Qt.NoItemFlags)
            self.test_list.addItem(item)

    def on_test_selected(self):
        """Handle test selection"""
        current_item = self.test_list.currentItem()
        if current_item and current_item.flags() & Qt.ItemIsEnabled:
            self.selected_test = current_item.text()
            self.playback_mode = True
            log.info(f"Selected test for playback: {self.selected_test}")
            self.accept()  # Close dialog and proceed

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
