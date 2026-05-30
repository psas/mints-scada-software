from PyQt5.QtWidgets import QPushButton, QLabel, QCheckBox
from nexus import GenericActuator
from gui import DeviceRow

class ActuatorRow(DeviceRow):
    def __init__(self, actor: GenericActuator, autopoll: bool = True):
        super().__init__(actor)
        self.actor = actor
        self.actor.poll()
        self.actor.addListener(self.onValueChange)
        
        self.nameLabel = QLabel(self.actor.name)
        self.addWidget(self.nameLabel)
        
        self.valueLabel = QLabel("label")
        self.addWidget(self.valueLabel)

        self.addStretch()

        self.autopollcheck = QCheckBox("Autopoll")
        self.addWidget(self.autopollcheck)
        self.autopollcheck.setChecked(self.actor.autopoll)
        self.autopollcheck.clicked.connect(self.pollCheckboxCheck)

        self.onButton = QPushButton("On")
        self.onButton.clicked.connect(self.buttonClickOn)
        self.addWidget(self.onButton)

        self.offButton = QPushButton("Off")
        self.offButton.clicked.connect(self.buttonClickOff)
        self.addWidget(self.offButton)

        self.updateButton = QPushButton("Update")
        self.updateButton.clicked.connect(self.buttonClick)
        self.addWidget(self.updateButton)

    def pollCheckboxCheck(self):
        self.actor.autopoll = self.autopollcheck.isChecked()

    def onValueChange(self, actor):
        self.valueLabel.setText(f"Value: {self.actor.value if self.actor.value is not None else 'error'}")
        
    def buttonClick(self):
        self.valueLabel.setText(f"Value: reading")
        self.actor.poll()

    def buttonClickOn(self):
        self.actor.set(True)

    def buttonClickOff(self):
        self.actor.set(False)