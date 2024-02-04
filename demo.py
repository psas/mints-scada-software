#!.venv/bin/python

# To install: Set up new venv
# Open terminal
# $ python -m venv .venv 
# $ .venv/bin/activate
# $ pip install -r requirements.txt

# To use later:
# Open terminal
# $ .venv/bin/activate

from PyQt5 import QtWidgets
# from PyQt5.QtWidgets import QApplication, QMainWindow, QDialog, QHBoxLayout, QPushButton, QLabel
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtCore import Qt
import sys

import settings

from sensor_bus import SensorBus

from sensor import Sensor

# Stock slcan firmware on Linux

class CanDemo(QDialog):
    def __init__(self, sensor, parent=None):
        super(CanDemo, self).__init__(parent)

        self.sensor = sensor

        self.setWindowTitle("CAN bus sensor demo")
        self.setGeometry(0, 0, 640, 480)

        # Force the style to be the same on all OSs:
        QApplication.setStyle("Fusion")

        # Now use a palette to switch to dark colors:
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ToolTipBase, Qt.white)
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        QApplication.setPalette(palette)

        mainLayout = QVBoxLayout()

        def buttonClick():
            tc.readValue(timeout=1)
            self.valueLabel.setText(f"Value: {self.sensor.value or 'error'}")

        self.updateButton = QPushButton("Button!")
        self.updateButton.clicked.connect(buttonClick)
        mainLayout.addWidget(self.updateButton)

        self.valueLabel = QLabel("label")
        mainLayout.addWidget(self.valueLabel)

        self.setLayout(mainLayout)

        self.tc = Sensor(0x64)

    def update(self):
        pass
        # win.show()
        # self.exec_()
    # sys.exit()

    # print("sending")
    # msg = DataPacket(0x32, [0x0, 0x25, 0x20, 0x1, 0x3, 0x1, 0x4, 0x1])
    # msg.send(bus)
    # m = DataPacket(bus.recv())
    # m.print()

# Demo thermocouple lives at 0x64
    # tc = Sensor(0x64, bus)
    # listeners.append(tc)
    # print("Polling sensor")
    # dt = tc.poll()
    # print("Waiting a moment for the result")
    # time.sleep(1)
    # print("Sensor value is " + str(tc.value))
    # print("Aux value is " + str(tc.aux))

    # # time.sleep(10)
    # exit()
        
with SensorBus(settings.sender, settings.bitrate) as bus:
    tc = Sensor(0x64)
    bus.addRider(tc)

    app = QApplication(sys.argv)
    demo = CanDemo(tc)
    demo.show()
    sys.exit(app.exec())