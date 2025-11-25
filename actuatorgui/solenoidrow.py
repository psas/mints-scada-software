from actuatorgui.actuatorrow import ActuatorRow, LEDIndicator
from actuators import Solenoid

class SolenoidRow(ActuatorRow):
    def __init__(self, actor: Solenoid):
        super().__init__(actor=actor)
        self.onButton.setText("OPEN")
        self.offButton.setText("CLOSE")

        # Update tooltips for solenoid-specific actions
        self.onButton.setToolTip("Open solenoid valve")
        self.offButton.setToolTip("Close solenoid valve")

    def onValueChange(self, sensor):
        """Update display when solenoid state changes"""
        if self.actor.state is not None:
            if self.actor.state:
                self.led.set_on()
                self.valueLabel.setText("OPEN")
            else:
                self.led.set_off()
                self.valueLabel.setText("CLOSED")
        else:
            self.led.set_unknown()
            self.valueLabel.setText("Error")

    def buttonClickOn(self):
        """Open the solenoid"""
        self.actor.setOpen(True)

    def buttonClickOff(self):
        """Close the solenoid"""
        self.actor.setOpen(False)