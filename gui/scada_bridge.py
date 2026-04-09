# gui/scada_bridge.py

import logging

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)


class ScadaBridge(QObject):
    valve_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    @pyqtSlot(str)
    def valveClicked(self, valve_id):
        logger.info("[SCADA] SVG clicked: %s", valve_id)
        self.valve_clicked.emit(valve_id)