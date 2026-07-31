from logging import getLogger
import sys
from time import sleep
from box import Box

import can
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

log = getLogger(__name__)

SETTINGS = Box.from_toml(filename="settings.toml")

NODE_ID_MASK = 0x7F

CLAIM_NODE_MSG_ID = 0x180
REQUEST_MSG_ID = 0x200
RESPONSE_MSG_ID = 0x280

SEQ_BYTE = 0
CMD_BYTE = 1
DATA_BYTE = 2


class BackendApi(QObject):
    sigMessage = Signal(object)
    sigError = Signal(str)

    def __init__(self, channel: str):
        super().__init__()
        log.debug("Initializing backend API")
        try:
            self.bus = can.ThreadSafeBus(
                interface=SETTINGS.can.interface,
                channel=SETTINGS.can.channel if channel is None else channel,
                bitrate=SETTINGS.can.bitrate,
            )
        except OSError as e:
            log.error("Unable to connect to CAN bus -- %s", e.strerror)
            sys.exit(e.errno)

        self._pool = QThreadPool.globalInstance()
        self._recv_task: CANReceiveTask | None = None

    def start(self):
        """Begin sending and receiving CAN messages on a pooled thread."""
        if self._recv_task is not None:
            return  # already running
        self._recv_task = CANReceiveTask(self.bus)
        self._send_task = CANSendTask(self.bus)
        self._recv_task.signals.sigMessage.connect(self.sigMessage.emit)
        self._recv_task.signals.sigError.connect(self.sigError.emit)
        self._pool.start(self._recv_task)
        self._pool.start(self._send_task)

    def stop(self):
        if self._recv_task is None:
            return
        self._recv_task.stop()
        self._recv_task = None

        if self._send_task is None:
            return
        self._send_task.stop()
        self._send_task = None

    def send(self, msg: can.Message):
        self.bus.send(msg)

    def shutdown(self):
        self.stop()
        self._pool.waitForDone(2000)
        self.bus.shutdown()


class CANReceiveSignals(QObject):
    sigMessage = Signal(object)  # emits can.Message
    sigError = Signal(str)


class CANReceiveTask(QRunnable):
    def __init__(self, bus: can.BusABC):
        super().__init__()
        self.bus = bus
        self.signals = CANReceiveSignals()
        self._running = True

    @Slot()
    def run(self):
        while self._running:
            try:
                msg: can.Message | None = self.bus.recv(timeout=2.0)
                if msg is None:
                    log.warning("Timed out waiting for a message on the CAN bus")
                    continue

                id = msg.arbitration_id
                data = msg.data
                log.debug("received CAN msg -- id: %s data: %s", id, data)
                self.signals.sigMessage.emit(msg)

            except can.CanError as e:
                log.error("CAN receive error: %s", e)
                self.signals.sigError.emit(str(e))
                continue

    def stop(self):
        self._running = False


class CANSendSignals(QObject):
    sigError = Signal(str)


class CANSendTask(QRunnable):
    def __init__(self, bus: can.BusABC):
        super().__init__()
        self.bus = bus
        self.signals = CANSendSignals()
        self._running = True

    @Slot()
    def run(self):
        while self._running:
            try:
                msg = can.Message(is_extended_id=False, arbitration_id=0x01, data=[0, 0, 0, 0, 0, 0, 0, 0])
                self.bus.send(msg)
                sleep(1)

            except can.CanError as e:
                log.error("CAN send error: %s", e)
                self.signals.sigError.emit(str(e))

    def stop(self):
        self._running = False


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
