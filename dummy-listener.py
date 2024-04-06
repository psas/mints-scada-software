import can
from datapacket import DataPacket
from sensor import Sensor
from sensorbus import SensorBus
import settings

myid = 0x32

with SensorBus(settings.receiver, settings.bitrate, print=True) as bus:
    tc = Sensor(0x32, simulated=True)
    tc.value = 33325
    bus.addRider(tc)
    print("Press enter to exit")
    input()

# with can.interface.Bus(bustype='slcan', channel=settings.receiver, bitrate=settings.bitrate) as bus:
#     while True:
#         m = DataPacket(bus.recv())
#         if m.id == myid:
#             print("4me!")
#             m.print()

#             cmd = m.data[0]

#             if cmd == 0x00:
#                 # Who are you? command
#                 m.err = False
#                 m.reply = True
#                 m.data = [0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0]
#                 m.send(bus)
#                 m.print()
#             else:
#                 # Unknown command
#                 m.err = True
#                 m.reply = True
