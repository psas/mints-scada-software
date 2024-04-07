from sensorgui import SensorRow
from sensors import Thermocouple

class ThermocoupleRow(SensorRow):
    def __init__(self, sensor: Thermocouple):
        super().__init__(sensor=sensor)

    def onValueChange(self, sensor):
        self.valueLabel.setText(f"Value: {f'{self.sensor.c:.1f}c' or 'error'}")