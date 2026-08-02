from secrets import randbits
import sys
from logging import getLogger
from typing import Self
import can
from PySide6.QtCore import QObject, QThreadPool, Signal

from config import config as CFG
from mints_backend.tasks import CANSendTask

log = getLogger(__name__)

NODE_ID_MASK = 0x7F

ERR_MSG_ID = 0x80
CLAIM_NODE_MSG_ID = 0x180
REQUEST_MSG_ID = 0x200
RESPONSE_MSG_ID = 0x280

CORELLATION_ID_BYTE = 0
CMD_BYTE = 1
DATA_BYTES = 2


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

        self.notifier = can.Notifier(self.bus, [self.sig_rx_message.emit])
        self._pool = QThreadPool.globalInstance()
        self._send_task: CANSendTask | None = None
        self.sig_rx_message.connect(self.on_rx)

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

    def on_rx(self, msg: can.Message):
        print(msg.data)
        packet = DataPacket.from_can_message(msg)
        print(packet.data.to_bytes())
        msg0 = packet.to_can_message()
        print(msg0.data)
        self.__send(msg0)
        # packet0 = DataPacket.from_can_message(msg0)
        # print(packet0)

    def __on_tx_error(self, err_msg: str):
        log.error("%s", err_msg)

    def shutdown(self):
        self.__stop()
        self.bus.shutdown()
        self._pool.waitForDone(250)


class CANData:
    def __init__(self, correlation_id: int | None, cmd: int, bytes: bytearray):
        if len(bytes) != 6:
            print(len(bytes))
            raise ValueError("length of CANData bytes must be exactly 6")

        self.correlation_id = (
            correlation_id if correlation_id is not None else randbits(8)
        )
        self.cmd = cmd
        self.bytes = bytes

    def to_bytes(self) -> bytearray:
        data = bytearray([0] * 8)
        data[CORELLATION_ID_BYTE] = self.correlation_id
        data[CMD_BYTE] = self.cmd
        data[DATA_BYTES:] = self.bytes
        return data

    def __repr__(self):
        return f"[{hex(self.cmd)}, [{', '.join(hex(byte) for byte in self.bytes)}]]"


class DataPacket:
    def __init__(self, id: int, is_err: bool, data: CANData):
        self.id = id
        self.is_err = is_err
        self.data = data

    @classmethod
    def from_can_message(cls, msg: can.Message) -> Self:
        id = msg.arbitration_id
        is_err = msg.arbitration_id & ~NODE_ID_MASK == ERR_MSG_ID
        data = CANData(
            msg.data[CORELLATION_ID_BYTE], msg.data[CMD_BYTE], msg.data[DATA_BYTES:]
        )
        return cls(id, is_err, data)

    def to_can_message(self) -> can.Message:
        return can.Message(
            is_extended_id=False, arbitration_id=self.id, data=self.data.to_bytes()
        )

    def __repr__(self):
        return f"[id: {hex(self.id)}, is_err: {self.is_err}, data: {self.data}]"
