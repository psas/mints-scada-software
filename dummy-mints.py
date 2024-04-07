import settings
from nexus import Bus, GenericSensor, GenericActuator

myid = 0x64

count = -1
def s2v():
    global count
    count += 1
    return count

with Bus(channel=settings.receiver, bitrate=settings.bitrate, dbgprint=True) as sb:
    tc = GenericSensor(myid, simulated=True)
    sb.addRider(tc)
    
    tc2 = GenericSensor(myid+1, simulated=True, genVal=s2v)
    sb.addRider(tc2)
    
    ac = GenericActuator(myid+2, simulated=True)
    sb.addRider(ac)
    
    print("Press enter to exit")
    input()