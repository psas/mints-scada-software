import sys
from PyQt5.QtWidgets import QApplication

from nexus import Bus, GenericSensor, GenericActuator
from sensors import Thermocouple
from sensorgui import MainWindow, SensorRow, ThermocoupleRow, ActuatorRow

import settings

# Should be compatable with any slcan CANBus interface on Linux
with Bus(settings.sender, settings.bitrate, dbgprint=True) as bus:
    app = QApplication(sys.argv)
    window = MainWindow()

    tc = GenericSensor(0x64)
    bus.addRider(tc)
    tcr = SensorRow(tc)
    window.mainLayout.addLayout(tcr)

    tc2 = Thermocouple(0x65)
    bus.addRider(tc2)
    tcr2 = ThermocoupleRow(tc2)
    window.mainLayout.addLayout(tcr2)

    ac = GenericActuator(0x66)
    bus.addRider(ac)
    act = ActuatorRow(ac)
    window.mainLayout.addLayout(act)


    window.mainLayout.addStretch()

    window.show()
    sys.exit(app.exec())