#!.venv/bin/python
import can
import threading
import time

import settings

from datapacket import DataPacket

from sensor import Sensor

running = True
startedEvent = threading.Event()
listeners = []

def receive(bus):
    print("Receiver running")
    startedEvent.set()
    while running:
        if bus is not None:
            bm = bus.recv(0.1)
            if bm is not None:
                p = DataPacket(bm)
                print("Got packet")
                p.print()
                for l in listeners:
                    l.onPacket(p)
        else:
            print("Bus was None! bad! Exiting listener")
            break

# Stock slcan firmware on Linux

receiver = None

def exit():
    global running
    print("Exiting")
    running = False
    receiver.join()
    print("Bye bye")

def startReceiver(bus):
    global receiver
    receiver = threading.Thread(target=receive, args=(bus,), name="CAN-receiver")
    receiver.start()
    startedEvent.wait()

with can.ThreadSafeBus(bustype='slcan', channel=settings.sender, bitrate=settings.bitrate) as bus:

    startReceiver(bus)

    # print("sending")
    # msg = DataPacket(0x32, [0x0, 0x25, 0x20, 0x1, 0x3, 0x1, 0x4, 0x1])
    # msg.send(bus)
    # m = DataPacket(bus.recv())
    # m.print()

# Demo thermocouple lives at 0x64
    tc = Sensor(0x64, bus)
    listeners.append(tc)
    print("Polling sensor")
    dt = tc.poll()
    print("Waiting a moment for the result")
    time.sleep(1)
    print("Sensor value is " + str(tc.value))
    print("Aux value is " + str(tc.aux))

    # time.sleep(10)
    exit()