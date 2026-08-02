from secrets import randbits
from typing import Self

import can

NODE_ID_MASK = 0x7F

ERR_MSG_ID = 0x80
CLAIM_NODE_MSG_ID = 0x180
REQUEST_MSG_ID = 0x200
RESPONSE_MSG_ID = 0x280

CORELLATION_ID_BYTE = 0
CMD_BYTE = 1
DATA_BYTES = 2

CAN_DATA_LEN = 6


class CANData:
    def __init__(self, correlation_id: int | None, cmd: int, bytes: bytearray):
        if len(bytes) != CAN_DATA_LEN:
            print(len(bytes))
            raise ValueError(f"length of CANData bytes must be exactly {CAN_DATA_LEN}")

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
        try:
            data = CANData(
                msg.data[CORELLATION_ID_BYTE], msg.data[CMD_BYTE], msg.data[DATA_BYTES:]
            )
            return cls(id, is_err, data)
        except ValueError as e:
            raise ValueError from e

    def to_can_message(self) -> can.Message:
        return can.Message(
            is_extended_id=False, arbitration_id=self.id, data=self.data.to_bytes()
        )

    def __repr__(self):
        return f"[id: {hex(self.id)}, is_err: {self.is_err}, data: {self.data}]"
