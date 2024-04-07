import sys
from PyQt5.QtWidgets import QApplication

from nexus import Bus, GenericSensor, GenericActuator
from sensors import Thermocouple
from sensorgui import MainWindow, SensorRow, ThermocoupleRow
from actuators import Solenoid
from actuatorgui import ActuatorRow, SolenoidRow

import settings

baseaddr = 0x64

# Should be compatable with any slcan CANBus interface on Linux
with Bus(settings.sender, settings.bitrate, dbgprint=True) as bus:
    app = QApplication(sys.argv)
    window = MainWindow()

    tc = GenericSensor(baseaddr)
    bus.addRider(tc)
    tcr = SensorRow(tc)
    window.mainLayout.addLayout(tcr)

    tc2 = Thermocouple(baseaddr+1)
    bus.addRider(tc2)
    tcr2 = ThermocoupleRow(tc2)
    window.mainLayout.addLayout(tcr2)

    ac = GenericActuator(baseaddr+2)
    bus.addRider(ac)
    act = ActuatorRow(ac)
    window.mainLayout.addLayout(act)

    ac2 = Solenoid(baseaddr+3)
    bus.addRider(ac2)
    ac2t = SolenoidRow(ac2)
    window.mainLayout.addLayout(ac2t)
    
    window.mainLayout.addStretch()

    window.show()
    sys.exit(app.exec())