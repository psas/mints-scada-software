import can
import threading
import time

from datapacket import DataPacket

class SensorBus():
    def __init__(self, channel, bitrate, bustype='slcan'):
        self.__running = True
        self.__startedEvent = threading.Event()
        self.__listeners = []
        self.__canbus = can.ThreadSafeBus(bustype=bustype, channel=channel, bitrate=bitrate)
        self.__receiverThread = threading.Thread(target=self.__receive, args=(self.__canbus,), name="CAN-receiver")
        
    def __enter__(self):
        self.open()
        return self

    def open(self):
        self.__receiverThread.start()
        self.__startedEvent.wait()

    def __exit__(self, *exec_info):
        self.close()

    def close(self):
        self.__running = False
        if self.__receiverThread is not None:
            self.__receiverThread.join()
        self.__canbus.shutdown()

    def __receive(self, canbus):
        print("Receiver running")
        self.__startedEvent.set()
        while self.__running:
            if canbus is not None:
                bm = canbus.recv(0.1)
                if bm is not None:
                    p = DataPacket(bm)
                    print("Got packet")
                    p.print()
                    for l in self.__listeners:
                        l.onPacket(p)
            else:
                print("CAN bus was None! bad! Exiting listener")
                break
        print("Receiver stopped")

    def addRider(self, rider):
        rider.setBus(self.__canbus)
        self.__listeners.append(rider)

    def removeRider(self, rider):
        if rider in self.__listeners:
            self.__listeners.remove(rider)
            rider.setBus(None)
