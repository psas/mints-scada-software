import can
from message import DataPacket

# Stock slcan firmware on Linux

bitrate = 1000000

with can.interface.Bus(bustype='slcan', channel='/dev/ttyACM1', bitrate=bitrate) as bus:
    msg = DataPacket(0x32, [0x0, 0x25, 0x20, 0x1, 0x3, 0x1, 0x4, 0x1])
    msg.send(bus)
    m = DataPacket(bus.recv())
    m.print()