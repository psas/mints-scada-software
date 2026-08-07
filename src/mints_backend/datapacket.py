from enum import Enum, unique
from typing import Self

import can

BASE_ID_MSK = int("11100000000", 2)
NODE_ID_MSK = int("00011110000", 2)
SUB_ID_MSK  = int("00000001111", 2)  # fmt: skip
ADDR_MSK = NODE_ID_MSK | SUB_ID_MSK

ERR_MSG_ID = 0x100  # 1 << 8
CLAIM_NODE_MSG_ID = 0x200  # 2 << 8
REQUEST_MSG_ID = 0x300  #  3 << 8
RESPONSE_MSG_ID = 0x400  # 4 << 8
# 0x500 / 5 << 8 unused
# 0x600 / 6 << 8 unused
# 0x700 / 7 << 8 unused

CAN_DATA_LEN = 7

CMD_POS = 0
DATA_POS = 1
OUTPUT_SET_POS = CAN_DATA_LEN - 1


@unique
class CANCmd(Enum):
    WriteReg = 1
    ReadReg = 2
    SetOutput = 3
    GetOutput = 4


class CANData:
    def __init__(self, cmd: CANCmd | None, bytes: bytearray):
        if len(bytes) != CAN_DATA_LEN:
            raise ValueError(f"length of CANData bytes must be exactly {CAN_DATA_LEN}")

        self.cmd = cmd if cmd else None
        self.bytes = bytes

    def to_bytes(self) -> bytearray:
        data = bytearray([0] * 8)
        data[CMD_POS] = self.cmd.value if self.cmd else 0
        data[DATA_POS:] = self.bytes
        return data

    def __repr__(self):
        return f"[{hex(self.cmd.value if self.cmd else 0)}, [{', '.join(hex(byte) for byte in self.bytes)}]]"


class DataPacket:
    def __init__(self, id: int, is_err: bool, data: CANData):
        self.id = id
        self.is_err = is_err
        self.data = data

    @classmethod
    def from_can_message(cls, msg: can.Message) -> Self:
        id = msg.arbitration_id
        is_err = msg.arbitration_id & BASE_ID_MSK == ERR_MSG_ID
        try:
            cmd = CANCmd(msg.data[CMD_POS])
        except ValueError:
            cmd = None
        data = CANData(cmd, msg.data[DATA_POS:])
        return cls(id, is_err, data)

    def to_can_message(self) -> can.Message:
        return can.Message(
            is_extended_id=False, arbitration_id=self.id, data=self.data.to_bytes()
        )

    def __repr__(self):
        return f"[id: {hex(self.id)}, is_err: {self.is_err}, data: {self.data}]"
