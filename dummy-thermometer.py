from datapacket import DataPacket
import settings
from sensorbus import SensorBus
from sensor import Sensor

myid = 0x64

count = -1
def s2v():
    global count
    count += 1
    return count

with SensorBus(channel=settings.receiver, bitrate=settings.bitrate, dbgprint=True) as sb:
    tc = Sensor(myid, simulated=True)
    tc2 = Sensor(myid+1, simulated=True, genVal=s2v)
    sb.addRider(tc)
    sb.addRider(tc2)
    print("Press enter to exit")
    input()
    


# with can.interface.Bus(bustype='slcan', channel=settings.receiver, bitrate=settings.bitrate) as bus:
#     while True:
#         m = DataPacket(bus.recv())
#         if m.id == myid:
#             print("4me!")
#             m.print()

#             cmd = m.data[1]

#             if cmd == 0x00:
#                 # Who are you? command
#                 m.err = False
#                 m.reply = True
#                 m.data = [m.data[0], 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0]
#                 m.send(bus)
#                 m.print()
#             # Read the sensor and then send a reply
#             elif cmd == 0x80:
#                 print("Reading ...")
#                 time.sleep(0.1)
#                 r = DataPacket(id=myid, reply=True, data=bytearray(random.randbytes(5)))
#                 r.data[0] = m.data[0]
#                 r.send(bus)
#                 print("Sent reply")
#             else:
#                 print("Unknown command")
#                 m.print()
#                 # Unknown command
#                 m.err = True
#                 m.reply = True
#                 m.send(bus)
