import random
from time import monotonic

import can

from config import config as CFG
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
from mints_backend.device_manager import DeviceManager, Output, Sensor

device_manager = DeviceManager(CFG["can"]["channel"])
outputs = {}
for dev in device_manager.device_registry.values():
    match dev:
        case Output():
            outputs[dev.id] = False

        case _:
            pass

# We just want the devices, not the bus
device_manager.notifier.stop()
device_manager.bus.shutdown()


def main():
    print(f"Listening for requests on {CFG['can']['channel']}")
    with can.Bus(
        interface=CFG["can"]["interface"],
        channel=CFG["can"]["channel"],
        bitrate=CFG["can"]["bitrate"],
    ) as bus:
        try:
            while True:
                msg: can.Message | None = bus.recv()
                if msg is None:
                    continue

                req_addr = msg.arbitration_id & ADDR_MSK
                req_device = device_manager.device_registry[req_addr]

                handle_can_rx(msg, req_device, bus)
        except KeyboardInterrupt:
            print("\nGoodbye")


def handle_can_rx(msg: can.Message, req_device: Sensor | Output, bus: can.BusABC):
    base_id = msg.arbitration_id & BASE_ID_MSK

    if base_id != REQUEST_MSG_ID:
        return

    request_datapacket = DataPacket.from_can_message(msg)
    resp_id = (msg.arbitration_id & ~BASE_ID_MSK) | RESPONSE_MSG_ID
    resp_val = None

    match CANCmd(request_datapacket.data.cmd):
        case CANCmd.ReadReg:
            resp_val = bytearray([int(random.gauss(3))] * CAN_DATA_LEN)

        case CANCmd.WriteReg:
            resp_val = bytearray([int(random.gauss(3))] * CAN_DATA_LEN)

        case CANCmd.SetOutput:
            val = request_datapacket.data.bytes[OUTPUT_SET_POS]
            outputs[req_device.id] = val
            resp_val = bytearray(CAN_DATA_LEN)
            resp_val[OUTPUT_SET_POS] = outputs[req_device.id]
            print(f"{monotonic()}: set output {hex(req_device.id)} to {val}")

        case CANCmd.GetOutput:
            resp_val = bytearray(CAN_DATA_LEN)
            resp_val[OUTPUT_SET_POS] = outputs[req_device.id]

    if resp_val is not None:
        resp_data = CANData(cmd=None, bytes=resp_val)
        resp_datapacket = DataPacket(id=resp_id, is_err=False, data=resp_data)
        bus.send(resp_datapacket.to_can_message())


if __name__ == "__main__":
    main()
