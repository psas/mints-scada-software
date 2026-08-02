from logging import getLogger
from queue import Full, Queue, ShutDown
import can
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from config import config as CFG

log = getLogger(__name__)


class CanBus(QObject):
    sig_rx_message = Signal(can.Message)
    sig_rx_error = Signal(str)
    _sig_tx_message = Signal(can.Message)
    sig_tx_error = Signal(str)

    def __init__(self, channel: str):
        super().__init__()
        log.debug("Initializing CAN bus")
        try:
            self.bus = can.ThreadSafeBus(
                interface=CFG["can"]["interface"],
                channel=CFG["can"]["channel"] if channel is None else channel,
                bitrate=CFG["can"]["bitrate"],
            )
        except OSError as e:
            raise OSError from e

        self.notifier = can.Notifier(self.bus, [self.sig_rx_message.emit])
        self._pool = QThreadPool.globalInstance()
        self._send_task: CANSendTask | None = None

    def start(self):
        """Begin sending and receiving CAN messages on a pooled thread."""
        if self._send_task is not None:
            log.error("Attempt to start already running CAN bus")
            return
        self._send_task = CANSendTask(self.bus)
        self._sig_tx_message.connect(self._send_task.enqueue_msg_tx)
        self._send_task.signals.sig_tx_error.connect(self.__on_tx_error)
        self._pool.start(self._send_task)

    def __stop(self):
        self.notifier.stop()
        if self._send_task is None:
            return
        self._send_task.stop()
        self._send_task = None

    def __send(self, msg: can.Message):
        self._sig_tx_message.emit(msg)

    def __on_tx_error(self, err_msg: str):
        log.error("%s", err_msg)

    def shutdown(self):
        self.__stop()
        self.bus.shutdown()
        self._pool.waitForDone(250)


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

    def enqueue_msg_tx(self, msg: can.Message):
        log.debug("Signal to send CAN msg received -- queuing message")
        try:
            self._queue.put_nowait(msg)
        except Full as e:
            self.signals.sig_tx_error.emit(f"Queue full -- dropping CAN msg -- {e}")

    def stop(self):
        self._running = False
        self._queue.shutdown(immediate=True)
