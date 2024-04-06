from nexus.datapacket import DataPacket
import settings
from nexus.bus import Bus
from nexus.genericsensor import GenericSensor

myid = 0x64

count = -1
def s2v():
    global count
    count += 1
    return count

with Bus(channel=settings.receiver, bitrate=settings.bitrate, dbgprint=True) as sb:
    tc = GenericSensor(myid, simulated=True)
    tc2 = GenericSensor(myid+1, simulated=True, genVal=s2v)
    sb.addRider(tc)
    sb.addRider(tc2)
    print("Press enter to exit")
    input()