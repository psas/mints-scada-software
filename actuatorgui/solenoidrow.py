from actuatorgui import ActuatorRow
from actuators import Solenoid

class SolenoidRow(ActuatorRow):
    def __init__(self, actor: Solenoid):
        super().__init__(actor=actor)
        self.onButton.setText("Open")
        self.offButton.setText("Close")

    def onValueChange(self, sensor):
        self.valueLabel.setText(f"Value: " + str("Open" if self.actor.state else "Closed") if self.actor.state is not None else 'error')

    def buttonClickOn(self):
        self.actor.setOpen(True)

    def buttonClickOff(self):
        self.actor.setOpen(False)