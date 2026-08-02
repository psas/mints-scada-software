import sys
from logging import getLogger
import can
from PySide6.QtCore import QObject, QThreadPool, Signal

from config import config as CFG
from mints_backend.tasks import CANSendTask

log = getLogger(__name__)


class BackendApi(QObject):
    sig_rx_message = Signal(can.Message)
    sig_rx_error = Signal(str)
    _sig_tx_message = Signal(can.Message)
    sig_tx_error = Signal(str)

    def __init__(self, channel: str):
        super().__init__()
        log.debug("Initializing backend API")
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
            log.error("Attempt to start already running API")
            return
        self._send_task = CANSendTask(self.bus)
        self._sig_tx_message.connect(self._send_task.on_msg_tx)
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
