import sys
import settings
from sensorbus import SensorBus
from sensor import Sensor
from mainwindow import MainWindow
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QPushButton, QLabel

class SensorRow(QHBoxLayout):
    def __init__(self, sensor):
        super(SensorRow, self).__init__()
        self.sensor = sensor

        self.updateButton = QPushButton("Button!")
        self.updateButton.clicked.connect(self.buttonClick)
        self.addWidget(self.updateButton)

        self.valueLabel = QLabel("label")
        self.addWidget(self.valueLabel) 

    def buttonClick(self):
        self.sensor.readValue(timeout=1)
        self.valueLabel.setText(f"Value: {self.sensor.value or 'error'}")

with SensorBus(settings.sender, settings.bitrate) as bus:
    tc = Sensor(0x64)
    bus.addRider(tc)
    app = QApplication(sys.argv)
    tcr = SensorRow(tc)

    print("z")
    print("a")
    window = MainWindow()
    print("b")

    window.mainLayout.addLayout(tcr)
    print("b")

    window.show()
    sys.exit(app.exec())

# Stock slcan firmware on Linux


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
        
