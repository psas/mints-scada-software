import settings
from nexus import Bus, GenericSensor, GenericActuator
from sensors import Thermocouple
from actuators import Solenoid
myid = 0x64

count = -1
def s2v():
    global count
    count += 1
    return count

with Bus(channel=settings.receiver, bitrate=settings.bitrate, packetprinting=True) as sb:
    tc = GenericSensor(myid, simulated=True)
    sb.addRider(tc)
    
    tc2 = Thermocouple(myid+1, simulated=True, genVal=s2v)
    sb.addRider(tc2)
    
    ac = GenericActuator(myid+2, simulated=True)
    sb.addRider(ac)

    ac = Solenoid(myid+3, simulated=True)
    sb.addRider(ac)

    print("Press enter to exit")
    input()