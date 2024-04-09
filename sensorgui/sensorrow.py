from PyQt5.QtWidgets import QPushButton, QLabel
from nexus import GenericSensor
from gui import DeviceRow

class SensorRow(DeviceRow):
    def __init__(self, sensor: GenericSensor):
        super(SensorRow, self).__init__(sensor)
        self.sensor = sensor
        self.sensor.poll()
        self.sensor.addListener(self.onValueChange)

        self.nameLabel = QLabel(self.sensor.name)
        self.addWidget(self.nameLabel)

        self.valueLabel = QLabel("label")
        self.addWidget(self.valueLabel)

        self.addStretch()

        self.updateButton = QPushButton("Update")
        self.updateButton.clicked.connect(self.buttonClick)
        self.addWidget(self.updateButton)

    def onValueChange(self, sensor):
        self.valueLabel.setText(f"Value: {self.sensor.value if self.sensor.value is not None else 'error'}")

    def buttonClick(self):
        self.valueLabel.setText(f"Value: reading")
        self.sensor.poll()