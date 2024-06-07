import can
import threading
from nexus import DataPacket
import os.path as path
import time
import logging

class Bus():
    def __init__(self, channel, bitrate, bustype='slcan', packetprinting: bool = False, packetlogging: bool = False):
        self.log = logging.getLogger("bus")
        # If the bus is running. The bus starts when it is created, and can not be restarted once it stops
        self.__running = True
        # Everyone on the bus
        self._riders = []
        self._packetprint = packetprinting
        # Event to watch for the listener starting
        self.__startedEvent = threading.Event()
        # The underlying CAN bus
        self.__canbus = can.ThreadSafeBus(bustype=bustype, channel=channel, bitrate=bitrate)
        # The thread that handles incoming DataPackets
        self.__receiverThread = threading.Thread(target=self.__receive, args=(self.__canbus,), name="CAN-receiver")
        # Set up exception handeling
        self._exceptionHandlers = []
        self._doDefaultExcpetionHandler = True
        # The file to log all CAN messages to
        self._logfile = None
        # Generate filename if we're logging
        if packetlogging:
            self._logfile = f"./log/{time.strftime('%Y%m%d_%H:%M:%S', time.gmtime(time.time()))}"
            # Update file numbers if one already exists
            n = 2
            while path.exists(self._logfile):
                self._logfile = self._logfile + f".{n:d}"
                n += 1
            self._logfile += ".log"
        # The open file to write to for a log
        self._log = None

    def addExceptionHandler(self, exceptionHandler):
        self._exceptionHandlers.append(exceptionHandler)

    def removeExceptionHandler(self, exceptionHandler):
        self._exceptionHandlers.remove(exceptionHandler)

    def _defaultExceptionHandler(self, exception: Exception, fatal: bool):
        if fatal:
            raise exception
        else:
            self.log.warn("Bus has encountered a non-fatal exception!")
            self.log.warn(exception.__cause__)

    def handleException(self, exception: Exception, fatal: bool):
        for eh in self._exceptionHandlers:
            eh(self, exception, fatal)
        if self._doDefaultExcpetionHandler:
            self._defaultExceptionHandler(exception, fatal)

    def __enter__(self):
        ''' Enter a with block '''
        # Start logging if needed
        if self._logfile is not None:
            # Open the log file
            self._log = open(self._logfile, "w")
        # Start the bus
        self.__receiverThread.start()
        # Wait for it to warm up
        self.__startedEvent.wait()
        return self

    def __exit__(self, *exec_info):
        ''' Exit a with block '''
        self.stop()
        # Close the log cleanly
        if self._log is not None:
            self._log.close()

    def __receive(self, canbus: can.ThreadSafeBus):
        ''' incoming DataPacket processing thread '''
        self.log.info("Receiver running")
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
                self.printDbgPacket(p, "Got packet")
                for l in self._riders:
                    l._onPacket(p)
                if self._log:
                    self._log.write(p.getLogString())
                    self._log.flush()
        # When the thread stops
        self.log.info("Receiver stopped")

    def stop(self):
        ''' Stops the sensor bus cleanly and releases all resources. The bus can not be restarted '''
        # Mark that the bus is no longer running
        self.__running = False
        # Wait for the listener to cleanly exit
        self.__receiverThread.join()
        # Cleanly shut down the underlying CAN bus
        self.__canbus.shutdown()

    def addRider(self, rider):
        ''' Adds a new rider to the bus. The rider is given a reference to the underlying CAN bus and will be alerted any time a DataPacket arrives '''
        # Check if the bus is running
        if not self.__running:
            raise RuntimeError("The SensorBus has been stopped")
        # Add the rider
        rider._connectBus(self)
        self._riders.append(rider)

    def removeRider(self, rider):
        ''' Removes a new rider from the bus. The rider's reference to the underlying CAN bus is removed and will be no longer be alerted any time a DataPacket arrives '''
        # Checks if the bus is running
        if not self.__running:
            raise RuntimeError("The SensorBus has been stopped")
        # Removes the rider only if it exists
        if rider in self._riders:
            self._riders.remove(rider)
            rider._setBus(None)

    def send(self, message: DataPacket):
        if self.__running:
            try:
                self.__canbus.send(message.genCanMessage())
                if self._log:
                    self._log.write(message.getLogString())
                    self._log.flush()
            except Exception as e:
                # TODO make this resilient
                self.handleException(e, True)
        else:
            e = Exception("Bus is not running.")
            self.handleException(e, True)

    def printDbgPacket(self, packet, msg):
        if self._packetprint:
            print(f"{msg:10s} ", end='')
            print(packet)
