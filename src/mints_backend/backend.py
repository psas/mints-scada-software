import can
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class CANReceiveSignals(QObject):
    sigMessage = Signal(object)  # emits can.Message
    sigError = Signal(str)


class CANReceiveTask(QRunnable):
    """Long-running task: owns the receive loop, submitted once to the pool."""

    def __init__(self, bus: can.BusABC):
        super().__init__()
        self.bus = bus
        self.signals = CANReceiveSignals()
        self._running = True

    @Slot()
    def run(self):
        while self._running:
            try:
                msg = self.bus.recv(timeout=1.0)
                if msg is not None:
                    self.signals.sigMessage.emit(msg)
            except can.CanError as e:
                self.signals.sigError.emit(str(e))

    def stop(self):
        self._running = False


class BackendApi(QObject):
    sigMessage = Signal(object)
    sigError = Signal(str)

    def __init__(self, channel: str):
        super().__init__()
        self.bus = can.interface.Bus(
            interface="socketcan", channel=channel, bitrate=1000000
        )
        self._pool = QThreadPool.globalInstance()
        self._recv_task: CANReceiveTask | None = None

    def start(self):
        """Begin receiving CAN messages on a pooled thread."""
        if self._recv_task is not None:
            return  # already running
        self._recv_task = CANReceiveTask(self.bus)
        self._recv_task.signals.sigMessage.connect(self.sigMessage.emit)
        self._recv_task.signals.sigError.connect(self.sigError.emit)
        self._pool.start(self._recv_task)

    def stop(self):
        if self._recv_task is not None:
            self._recv_task.stop()
            self._recv_task = None

    def send_can_msg(self, msg: can.Message):
        self.bus.send(msg)

    def shutdown(self):
        self.stop()
        self._pool.waitForDone(2000)
        self.bus.shutdown()

