from PyQt5.QtWidgets import QPushButton, QLabel, QFrame
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from nexus import GenericActuator
from gui import DeviceRow


class LEDIndicator(QLabel):
    """LED-style status indicator"""

    def __init__(self, parent=None):
        super().__init__("●", parent)
        self.setFont(QFont("Arial", 14))
        self.setFixedSize(20, 20)
        self.setAlignment(Qt.AlignCenter)
        self.set_unknown()

    def set_on(self):
        """Set LED to ON state (green)"""
        self.setStyleSheet("color: #4CAF50; font-weight: bold;")  # Green
        self.setToolTip("Status: ON")

    def set_off(self):
        """Set LED to OFF state (red)"""
        self.setStyleSheet("color: #F44336; font-weight: bold;")  # Red
        self.setToolTip("Status: OFF")

    def set_unknown(self):
        """Set LED to UNKNOWN state (gray)"""
        self.setStyleSheet("color: #757575; font-weight: bold;")  # Gray
        self.setToolTip("Status: Unknown")


class ActuatorRow(DeviceRow):
    def __init__(self, actor: GenericActuator):
        super().__init__(actor)
        self.actor = actor
        self.actor.poll()
        self.actor.addListener(self.onValueChange)

        # LED Status Indicator
        self.led = LEDIndicator()
        self.addWidget(self.led)

        # Name Label
        self.nameLabel = QLabel(self.actor.name)
        self.nameLabel.setFont(QFont("Arial", 10, QFont.Bold))
        self.nameLabel.setFixedWidth(150)
        self.addWidget(self.nameLabel)

        # Value Label (state display)
        self.valueLabel = QLabel("Unknown")
        self.valueLabel.setFont(QFont("Monospace", 9))
        self.valueLabel.setFixedWidth(100)
        self.addWidget(self.valueLabel)

        self.addStretch()

        # ON Button
        self.onButton = QPushButton("ON")
        self.onButton.setObjectName("onButton")
        self.onButton.clicked.connect(self.buttonClickOn)
        self.onButton.setToolTip("Turn device ON")
        self.onButton.setStyleSheet("""
            QPushButton {
                background-color: #31363b;
                color: #f4f4f4;
                border: 1px solid #4a4f55;
                border-left: 3px solid #4CAF50;
                border-radius: 3px;
                padding: 6px 12px;
                font-weight: bold;
                min-width: 60px;
            }
            QPushButton:hover {
                background-color: #2d4a2e;
            }
            QPushButton:pressed {
                background-color: #1a291a;
            }
        """)
        self.addWidget(self.onButton)

        # OFF Button
        self.offButton = QPushButton("OFF")
        self.offButton.setObjectName("offButton")
        self.offButton.clicked.connect(self.buttonClickOff)
        self.offButton.setToolTip("Turn device OFF")
        self.offButton.setStyleSheet("""
            QPushButton {
                background-color: #31363b;
                color: #f4f4f4;
                border: 1px solid #4a4f55;
                border-left: 3px solid #F44336;
                border-radius: 3px;
                padding: 6px 12px;
                font-weight: bold;
                min-width: 60px;
            }
            QPushButton:hover {
                background-color: #4a2d2d;
            }
            QPushButton:pressed {
                background-color: #291a1a;
            }
        """)
        self.addWidget(self.offButton)

        # Update Button
        self.updateButton = QPushButton("↻")
        self.updateButton.clicked.connect(self.buttonClick)
        self.updateButton.setToolTip("Refresh device status")
        self.updateButton.setFixedWidth(40)
        self.updateButton.setStyleSheet("""
            QPushButton {
                background-color: #31363b;
                color: #f4f4f4;
                border: 1px solid #4a4f55;
                border-radius: 3px;
                padding: 4px 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3a3f44;
            }
            QPushButton:pressed {
                background-color: #232629;
            }
        """)
        self.addWidget(self.updateButton)

        # Initialize display
        self.onValueChange(actor)

    def onValueChange(self, actor):
        """Update display when value changes"""
        if self.actor.value is not None:
            # Update LED
            if self.actor.value:
                self.led.set_on()
                self.valueLabel.setText("ON")
            else:
                self.led.set_off()
                self.valueLabel.setText("OFF")
        else:
            self.led.set_unknown()
            self.valueLabel.setText("Error")

    def buttonClick(self):
        """Handle update button click"""
        self.valueLabel.setText("Reading...")
        self.led.set_unknown()
        self.actor.poll()

    def buttonClickOn(self):
        """Handle ON button click"""
        self.actor.set(True)

    def buttonClickOff(self):
        """Handle OFF button click"""
        self.actor.set(False)