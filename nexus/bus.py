import can
import threading
from nexus import BusRider, DataPacket, dbgutils

class Bus():
    def __init__(self, channel, bitrate, bustype='slcan', dbgprint: bool = False):
        # If the bus is running. The bus starts when it is created, and can not be restarted once it stops
        self.__running = True
        # Everyone on the bus
        self.__riders = []
        self._print = dbgprint
        # Event to watch for the listener starting
        self.__startedEvent = threading.Event()
        # The underlying CAN bus
        self.__canbus = can.ThreadSafeBus(bustype=bustype, channel=channel, bitrate=bitrate)
        # The thread that handles incoming DataPackets
        self.__receiverThread = threading.Thread(target=self.__receive, args=(self.__canbus,), name="CAN-receiver")
        # Start the bus
        self.__receiverThread.start()
        # Wait for it to warm up
        self.__startedEvent.wait()
        
    def __enter__(self):
        ''' Enter a with block '''
        return self

    def __exit__(self, *exec_info):
        ''' Exit a with block '''
        self.stop()

    def __receive(self, canbus: can.ThreadSafeBus):
        ''' incoming DataPacket processing thread '''
        print("Receiver running")
        # Let the starting thread know this thread is actually running
        self.__startedEvent.set()
        # As long as this thread is supposed to be running
        while self.__running:
            # If the CAN bus is broke, break
            if canbus is None:
                raise RuntimeError("The CAN bus has broken")
            # Get the incoming data packet
            bm = canbus.recv(0.1)
            # Process the incoming DataPacket
            if bm is not None:
                p = DataPacket(bm)
                if(self._print):
                    print("Got packet")
                    p.print()
                for l in self.__riders:
                    l._onPacket(p)
        # When the thread stops
        print("Receiver stopped")

    def stop(self):
        ''' Stops the sensor bus cleanly and releases all resources. The bus can not be restarted '''
        # Mark that the bus is no longer running
        self.__running = False
        # Wait for the listener to cleanly exit
        self.__receiverThread.join()
        # Cleanly shut down the underlying CAN bus
        self.__canbus.shutdown()

    def addRider(self, rider: BusRider):
        ''' Adds a new rider to the bus. The rider is given a reference to the underlying CAN bus and will be alerted any time a DataPacket arrives '''
        # Check if the bus is running
        if not self.__running:
            raise RuntimeError("The SensorBus has been stopped")
        # Add the rider
        rider._connectBus(self.__canbus)
        self.__riders.append(rider)

    def removeRider(self, rider: BusRider):
        ''' Removes a new rider from the bus. The rider's reference to the underlying CAN bus is removed and will be no longer be alerted any time a DataPacket arrives '''
        # Checks if the bus is running
        if not self.__running:
            raise RuntimeError("The SensorBus has been stopped")
        # Removes the rider only if it exists
        if rider in self.__riders:
            self.__riders.remove(rider)
            rider._setBus(None)
