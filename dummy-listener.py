import can
from datapacket import DataPacket
import settings

myid = 0x32

with can.interface.Bus(bustype='slcan', channel=settings.receiver, bitrate=settings.bitrate) as bus:
    while True:
        m = DataPacket(bus.recv())
        if m.id == myid:
            print("4me!")
            m.print()

            cmd = m.data[0]

            if cmd == 0x00:
                # Who are you? command
                m.err = False
                m.reply = True
                m.data = [0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0]
                m.send(bus)
                m.print()
            else:
                # Unknown command
                m.err = True
                m.reply = True
