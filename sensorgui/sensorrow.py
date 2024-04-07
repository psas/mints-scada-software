from PyQt5.QtWidgets import QHBoxLayout, QPushButton, QLabel
from nexus import GenericSensor

class SensorRow(QHBoxLayout):
    def __init__(self, sensor: GenericSensor):
        super(SensorRow, self).__init__()
        self.sensor = sensor
        self.sensor.poll()
        self.sensor.addListener(self.onValueChange)

        self.updateButton = QPushButton("Update")
        self.updateButton.clicked.connect(self.buttonClick)
        self.addWidget(self.updateButton)

        self.valueLabel = QLabel("label")
        self.addWidget(self.valueLabel)

    def onValueChange(self):
        self.valueLabel.setText(f"Value: {self.sensor.value or 'error'}")

    def buttonClick(self):
        self.valueLabel.setText(f"Value: reading")
        self.sensor.poll()