from PyQt5.QtWidgets import QPushButton, QLabel, QCheckBox
from nexus import GenericSensor
from gui import DeviceRow

class SensorRow(DeviceRow):
    def __init__(self, sensor: GenericSensor):
        super(SensorRow, self).__init__(sensor)
        self.sensor = sensor
        self.sensor.poll()
        self.sensor.addListener(self.onValueChange)

        # Prepend the name with the ID
        self.nameLabel = QLabel(f"[{self.sensor.id :02X}] {self.sensor.name}")
        self.addWidget(self.nameLabel)

        self.valueLabel = QLabel("label")
        self.addWidget(self.valueLabel)

        self.addStretch()

        self.autopollcheck = QCheckBox("Autopoll")
        self.addWidget(self.autopollcheck)
        self.autopollcheck.setChecked(self.sensor.autopoll)
        self.autopollcheck.clicked.connect(self.pollCheckboxCheck)

        self.updateButton = QPushButton("Update")
        self.updateButton.clicked.connect(self.buttonClick)
        self.addWidget(self.updateButton)

    def pollCheckboxCheck(self):
        self.sensor.autopoll = self.autopollcheck.isChecked()

    def onValueChange(self, sensor):
        self.valueLabel.setText(f"Value: {self.sensor.value if self.sensor.value is not None else 'error'}")

    def buttonClick(self):
        self.valueLabel.setText(f"Value: reading")
        self.sensor.poll()