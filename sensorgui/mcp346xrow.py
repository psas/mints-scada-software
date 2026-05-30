from sensorgui import SensorRow
from sensors import MCP346x

class MCP346xRow(SensorRow):
    def __init__(self, sensor: MCP346x, **kwargs):
        super().__init__(sensor=sensor, **kwargs)
        self.sensor: MCP346x = sensor

    def onValueChange(self, sensor):
        self.valueLabel.setText(f"Voltage: {f'{self.sensor.v:.4f}v ({self.sensor.value})' or 'error'}")