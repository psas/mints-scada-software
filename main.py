import sys
from PyQt5.QtWidgets import QApplication

from nexus import Bus, GenericSensor
from sensors import Thermocouple
from sensorgui import MainWindow, SensorRow, ThermocoupleRow

import settings

# Should be compatable with any slcan CANBus interface on Linux
with Bus(settings.sender, settings.bitrate, dbgprint=True) as bus:
    app = QApplication(sys.argv)

    tc = GenericSensor(0x64)
    bus.addRider(tc)
    tcr = SensorRow(tc)

    tc2 = Thermocouple(0x65)
    bus.addRider(tc2)
    tcr2 = ThermocoupleRow(tc2)

    window = MainWindow()

    window.mainLayout.addLayout(tcr)
    window.mainLayout.addLayout(tcr2)
    window.mainLayout.addStretch()

    window.show()
    sys.exit(app.exec())