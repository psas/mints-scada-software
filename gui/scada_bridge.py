"""gui/scada_bridge.py

Qt bridge that forwards SCADA SVG click events into the PyQt signal layer.
"""

import logging

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)


class ScadaBridge(QObject):
    """Expose SCADA webpage events to Qt-side window code.

    The bridge receives slot calls from the SCADA webpage layer and re-emits
    them as Qt signals that controller code can connect to.
    """

    valve_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        """Initialize the SCADA bridge object.

        Args:
            parent: Optional Qt parent object.
        """
        super().__init__(parent)

    @pyqtSlot(str)
    def valveClicked(self, valve_id):
        """Log and forward a clicked SCADA valve identifier.

        Args:
            valve_id: SCADA valve element identifier emitted by the SVG/webpage
                layer.
        """
        logger.info("[SCADA] SVG clicked: %s", valve_id)
        self.valve_clicked.emit(valve_id)
