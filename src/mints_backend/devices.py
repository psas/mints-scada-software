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

log = getLogger(__name__)

UPDATE_PERIOD = 1.0


class Device(QObject):
    sig_value_received = Signal(int)

    def __init__(self, id: int, name: str, bus: can.BusABC):
        super().__init__()
        self.id = id
        self.name = name
        self.bus = bus

    def handle_can_rx(self, msg: can.Message):
        base_id = msg.arbitration_id & BASE_ID_MSK
        addr = msg.arbitration_id & ADDR_MSK
        if addr != self.id or base_id != RESPONSE_MSG_ID:
            return

        try:
            datapacket = DataPacket.from_can_message(msg)
        except ValueError:
            log.error("Sensor '%s' failed to parse datapacket from CAN msg", self.name)
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


class Sensor(Device):
    def __init__(self, id: int, name: str, kind: SensorKind, bus: can.BusABC):
        super().__init__(id, name, bus)
        self.kind = kind
        self.subscription: can.CyclicSendTaskABC | None = None
        self.num_sig_val_rcv_connections = 0

    def subscribe(self, slot_fn: Callable, send_period: float = UPDATE_PERIOD):
        data = CANData(CANCmd.ReadReg, bytearray([0] * CAN_DATA_LEN))
        id = self.id + REQUEST_MSG_ID
        datapacket = DataPacket(id=id, is_err=False, data=data)
        self.subscription = self.bus.send_periodic(
            datapacket.to_can_message(), send_period
        )
        self.sig_value_received.connect(slot_fn)
        self.num_sig_val_rcv_connections += 1

    def unsubscribe_all(self):
        if self.subscription is None:
            return
        self.subscription.stop()
        if self.num_sig_val_rcv_connections > 0:
            self.sig_value_received.disconnect()
            self.num_sig_val_rcv_connections = 0
        else:
            return

    @override
    def decode(self, datapacket: DataPacket) -> int:
        sum = 0
        for byte in datapacket.data.bytes:
            sum += byte
        return sum


class Output(Device):
    def __init__(self, id: int, name: str, bus: can.BusABC):
        super().__init__(id, name, bus)
        self.state: OutputState | None = None
        self.num_sig_val_rcv_connections = 0

    def set_state(self, state: OutputState) -> None:
        bytes = bytearray(CAN_DATA_LEN)
        bytes[OUTPUT_SET_POS] = state.value

        self.send_cmd(CANCmd.SetOutput, bytes)

    def get_state(self) -> None:
        self.send_cmd(CANCmd.GetOutput, bytearray(CAN_DATA_LEN))

    def add_slot_fn(self, slot_fn: Callable) -> None:
        self.sig_value_received.connect(slot_fn)
        self.num_sig_val_rcv_connections += 1

    def remove_all_slot_fns(self) -> None:
        if self.num_sig_val_rcv_connections > 0:
            self.sig_value_received.disconnect()
            self.num_sig_val_rcv_connections = 0

    def decode(self, datapacket: DataPacket) -> int:
        return datapacket.data.bytes[OUTPUT_SET_POS]
