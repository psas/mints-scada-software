import sys
from logging import getLogger

import can
from PySide6.QtCore import QObject, QThreadPool, Signal
from config import config as CFG

from mints_backend.tasks import CANReceiveTask, CANSendTask

log = getLogger(__name__)

NODE_ID_MASK = 0x7F

CLAIM_NODE_MSG_ID = 0x180
REQUEST_MSG_ID = 0x200
RESPONSE_MSG_ID = 0x280

SEQ_BYTE = 0
CMD_BYTE = 1
DATA_BYTE = 2


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
            log.error("Unable to connect to CAN bus -- %s", e.strerror)
            sys.exit(e.errno)

        self._pool = QThreadPool.globalInstance()
        self._recv_task: CANReceiveTask | None = None
        self._send_task: CANSendTask | None = None
        self.sig_rx_message.connect(self.__on_msg_rx)

    def start(self):
        """Begin sending and receiving CAN messages on a pooled thread."""
        if self._recv_task is not None or self._send_task is not None:
            log.error("Attempt to start already running API")
            return
        self._recv_task = CANReceiveTask(self.bus)
        self._send_task = CANSendTask(self.bus)
        self._recv_task.signals.sig_rx_message.connect(self.sig_rx_message.emit)
        self._recv_task.signals.sig_rx_error.connect(self.sig_rx_error.emit)
        self._sig_tx_message.connect(self._send_task.on_msg_tx)
        self._send_task.signals.sig_tx_error.connect(self.__on_tx_error)
        self._pool.start(self._recv_task)
        self._pool.start(self._send_task)

    def __stop(self):
        if self._recv_task is None:
            return
        self._recv_task.stop()
        self._recv_task = None

        if self._send_task is None:
            return
        self._send_task.stop()
        self._send_task = None

    def __send(self, msg: can.Message):
        self._sig_tx_message.emit(msg)

    def __on_tx_error(self, err_msg: str):
        log.error("%s", err_msg)

    def __on_msg_rx(self, msg: can.Message):
        id = msg.arbitration_id
        data = msg.data
        log.debug("Received CAN msg -- id: %s data: %s", id, data)

    def shutdown(self):
        self.__stop()
        self.bus.shutdown()
        self._pool.waitForDone(250)


class CANData:
    def __init__(self, seq: int, cmd: int, bytes: bytearray):
        self.seq = seq
        self.cmd = cmd
        self.bytes = bytes


class DataPacket:
    def __init__(self, msg: can.Message, err: int):
        data = msg.data
        self.id = msg.arbitration_id & NODE_ID_MASK
        self.err = err
        self.data = CANData(data[SEQ_BYTE], data[CMD_BYTE], data[DATA_BYTE:])
