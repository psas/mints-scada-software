from random import randbytes
import random

import can
from config import config as CFG
from mints_backend.device_manager import DeviceManager
from mints_backend.datapacket import (
    BASE_ID_MSK,
    CAN_DATA_LEN,
    REQUEST_MSG_ID,
    RESPONSE_MSG_ID,
    CANCmd,
    CANData,
    DataPacket,
)

device_manager = DeviceManager(CFG["can"]["channel"])
device_manager.notifier.add_listener(can.Printer())


def main():
    print(f"Listening for requests on {CFG['can']['channel']}")
    try:
        while True:
            msg: can.Message | None = device_manager.bus.recv()
            if msg is None:
                continue

            handle_can_rx(msg)
    except KeyboardInterrupt:
        print("Cleaning up...")
        device_manager.notifier.stop()
        device_manager.bus.shutdown()
        print("Goodbye")


def handle_can_rx(msg: can.Message):
    base_id = msg.arbitration_id & BASE_ID_MSK

    if base_id != REQUEST_MSG_ID:
        return

    request_datapacket = DataPacket.from_can_message(msg)
    resp_id = (msg.arbitration_id & ~BASE_ID_MSK) | RESPONSE_MSG_ID

    match request_datapacket.data.cmd:
        case CANCmd.ReadReg:
            resp_val = bytearray([int(random.gauss(3))] * CAN_DATA_LEN)

        case CANCmd.WriteReg:
            resp_val = bytearray([int(random.gauss(3))] * CAN_DATA_LEN)

        case CANCmd.SetOutput:
            resp_val = bytearray([int(random.gauss(3))] * CAN_DATA_LEN)

        case CANCmd.GetOutput:
            resp_val = bytearray([int(random.gauss(3))] * CAN_DATA_LEN)

        case _:
            print("Unhandled CANCmd type")
            return

    resp_data = CANData(cmd=None, bytes=resp_val)
    resp_datapacket = DataPacket(id=resp_id, is_err=False, data=resp_data)
    device_manager.bus.send(resp_datapacket.to_can_message())


if __name__ == "__main__":
    main()
