    
from PyQt5.QtWidgets import QHBoxLayout, QPushButton, QLabel
from nexus import BusRider

class DeviceRow(QHBoxLayout):
    def __init__(self, thing: BusRider):
        super().__init__()
        self._thing = thing