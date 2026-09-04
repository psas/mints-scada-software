from collections.abc import Callable
from logging import getLogger
from typing import override

import can
from PySide6.QtCore import QObject, Signal

from mints_backend.datapacket import (
    ADDR_MSK,
    BASE_ID_MSK,
    CAN_DATA_LEN,
    OUTPUT_SET_POS,
    REQUEST_MSG_ID,
    RESPONSE_MSG_ID,
    CANCmd,
    CANData,
    DataPacket,
)
from mints_backend.models import OutputState, SensorKind

logger = getLogger(__name__)

UPDATE_PERIOD = 1.0


class Device(QObject):
    sig_value_received = Signal(int)

    def __init__(self, id: int, name: str, bus: can.BusABC):
        super().__init__()
        self.id = id
        self.name = name
        self.bus = bus
        self.sig_val_recvrs: set[Callable] = set()

    def handle_can_rx(self, msg: can.Message):
        base_id = msg.arbitration_id & BASE_ID_MSK
        addr = msg.arbitration_id & ADDR_MSK
        if addr != self.id or base_id != RESPONSE_MSG_ID:
            return

        try:
            datapacket = DataPacket.from_can_message(msg)
        except ValueError:
            logger.error("%s failed to parse datapacket from CAN msg", self.name)
            return

        val = self.decode(datapacket)
        self.sig_value_received.emit(val)

    def send_cmd(self, cmd: CANCmd, cmd_params: bytearray):
        data = CANData(cmd, cmd_params)
        arbitration_id = REQUEST_MSG_ID | self.id
        datapacket = DataPacket(id=arbitration_id, is_err=False, data=data)
        self.bus.send(datapacket.to_can_message())

    def decode(self, _datapacket: DataPacket) -> int:
        raise NotImplementedError

    def add_recvr(self, slot_fn: Callable) -> None:
        self.sig_value_received.connect(slot_fn)
        self.sig_val_recvrs.add(slot_fn)

    def remove_recvr(self, slot_fn: Callable):
        if slot_fn not in self.sig_val_recvrs:
            logger.error(
                "Attempted to remove slot fn not connected to %s: %s",
                self.name,
                str(slot_fn),
            )
        self.sig_value_received.disconnect(slot_fn)
        self.sig_val_recvrs.remove(slot_fn)

    def remove_all_recvrs(self) -> None:
        for slot_fn in self.sig_val_recvrs:
            self.sig_value_received.disconnect(slot_fn)
        self.sig_val_recvrs.clear()


class Sensor(Device):
    def __init__(self, id: int, name: str, kind: SensorKind, bus: can.BusABC):
        super().__init__(id, name, bus)
        self.kind = kind
        self.send_task: can.CyclicSendTaskABC | None = None

    def begin_periodic_reads(self, send_period: float):
        data = CANData(CANCmd.ReadReg, bytearray([0] * CAN_DATA_LEN))
        id = self.id + REQUEST_MSG_ID
        datapacket = DataPacket(id=id, is_err=False, data=data)
        self.send_task = self.bus.send_periodic(
            datapacket.to_can_message(), send_period
        )

    def subscribe(self, slot_fn: Callable, send_period: float = UPDATE_PERIOD):
        if len(self.sig_val_recvrs) == 0:
            self.begin_periodic_reads(send_period)
        self.add_recvr(slot_fn)

    def unsubscribe(self, slot_fn: Callable) -> None:
        self.remove_recvr(slot_fn)
        if len(self.sig_val_recvrs) == 0:
            self.stop_send_task()

    def unsubscribe_all(self) -> None:
        self.stop_send_task()
        self.remove_all_recvrs()

    def stop_send_task(self) -> None:
        if self.send_task is None:
            logger.error("Attempted to stop non-running send task for %s", self.name)
            return

        self.send_task.stop()

    @override
    def decode(self, datapacket: DataPacket) -> int:
        sum = 0
        for byte in datapacket.data.bytes:
            sum += byte
        return sum


class Output(Device):
    def set_state(self, val: bool) -> None:
        bytes = bytearray(CAN_DATA_LEN)
        bytes[OUTPUT_SET_POS] = int(val)
        self.send_cmd(CANCmd.SetOutput, bytes)

    def get_state(self) -> None:
        self.send_cmd(CANCmd.GetOutput, bytearray(CAN_DATA_LEN))

    def decode(self, datapacket: DataPacket) -> int:
        return datapacket.data.bytes[OUTPUT_SET_POS]
