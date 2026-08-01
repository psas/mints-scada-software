import logging
from queue import Full, Queue, ShutDown

import can
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

log = logging.getLogger(__name__)


class CANSendSignals(QObject):
    sig_tx_error = Signal(str)


class CANSendTask(QRunnable):
    def __init__(self, bus: can.BusABC):
        super().__init__()
        self._bus = bus
        self.signals = CANSendSignals()
        self._queue: Queue[can.Message] = Queue(50)
        self._running = True

    @Slot()
    def run(self):
        while self._running:
            try:
                msg = self._queue.get()
                self._bus.send(msg)

            except ShutDown:
                break

            except can.CanError as e:
                log.error("CAN send error: %s", e)
                self.signals.sig_tx_error.emit(str(e))

    def on_msg_tx(self, msg: can.Message):
        log.debug("Signal to send CAN msg received -- queuing message")
        try:
            self._queue.put_nowait(msg)
        except Full as e:
            self.signals.sig_tx_error.emit(f"Queue full -- dropping CAN msg -- {e}")

    def stop(self):
        self._running = False
        self._queue.shutdown(immediate=True)
