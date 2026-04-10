# nexus/bus.py

"""CAN bus wrapper with rider callbacks, optional packet logging, and lifecycle helpers."""

import can
import threading
from nexus import DataPacket
import os.path as path
import time
import logging


class Bus:
    """Manage a thread-safe CAN bus session and fan out packets to registered riders.

    The bus owns the underlying ``python-can`` bus object, starts a background
    receive thread when entered as a context manager, forwards received
    ``DataPacket`` objects to connected riders, and optionally logs packet
    traffic to a timestamped file.
    """

    def __init__(
        self,
        channel,
        bitrate,
        bustype="slcan",
        packetprinting: bool = False,
        packetlogging: bool = False,
    ):
        """Initialize the CAN bus wrapper and optional debug/logging behavior.

        Args:
            channel: Bus channel passed to ``can.ThreadSafeBus``.
            bitrate: CAN bitrate passed to ``can.ThreadSafeBus``.
            bustype: Backend type for ``python-can``. Defaults to ``"slcan"``.
            packetprinting: Whether to print packets as they are received.
            packetlogging: Whether to log sent and received packets to a file
                under ``./log``.

        Returns:
            None.
        """
        self.log = logging.getLogger("bus")
        # If the bus is running. The bus starts when it is created, and can not be restarted once it stops
        self.__running = True
        # Everyone on the bus
        self._riders = []
        self._packetprint = packetprinting
        # Event to watch for the listener starting
        self.__startedEvent = threading.Event()
        # The underlying CAN bus
        self.__canbus = can.ThreadSafeBus(
            bustype=bustype, channel=channel, bitrate=bitrate
        )
        # The thread that handles incoming DataPackets
        self.__receiverThread = threading.Thread(
            target=self.__receive, args=(self.__canbus,), name="CAN-receiver"
        )
        # Set up exception handeling
        self._exceptionHandlers = []
        self._doDefaultExcpetionHandler = True
        # The file to log all CAN messages to
        self._logfile = None
        # Generate filename if we're logging
        if packetlogging:
            self._logfile = (
                f"./log/{time.strftime('%Y%m%d_%H:%M:%S', time.gmtime(time.time()))}"
            )
            # Update file numbers if one already exists
            n = 2
            while path.exists(self._logfile):
                self._logfile = self._logfile + f".{n:d}"
                n += 1
            self._logfile += ".log"
        # The open file to write to for a log
        self._log = None

    def addExceptionHandler(self, exceptionHandler):
        """Register an exception callback for bus send/receive failures.

        Args:
            exceptionHandler: Callable invoked as
                ``exceptionHandler(self, exception, fatal)``.

        Returns:
            None.
        """
        self._exceptionHandlers.append(exceptionHandler)

    def removeExceptionHandler(self, exceptionHandler):
        """Remove a previously registered exception callback.

        Args:
            exceptionHandler: Previously registered exception callback.

        Returns:
            None.
        """
        self._exceptionHandlers.remove(exceptionHandler)

    def _defaultExceptionHandler(self, exception: Exception, fatal: bool):
        """Handle bus exceptions when default exception handling is enabled.

        Fatal exceptions are re-raised immediately. Non-fatal exceptions are
        logged through the bus logger.

        Args:
            exception: Exception raised by bus activity.
            fatal: Whether the exception should terminate the caller.

        Raises:
            Exception: Re-raises ``exception`` when ``fatal`` is True.
        """
        if fatal:
            raise exception
        else:
            self.log.warn("Bus has encountered a non-fatal exception!")
            self.log.warn(exception.__cause__)

    def handleException(self, exception: Exception, fatal: bool):
        """Dispatch a bus exception to custom handlers and the default handler.

        Args:
            exception: Exception raised by bus activity.
            fatal: Whether the exception should be treated as fatal.

        Returns:
            None.

        Raises:
            Exception: Propagates from the default handler when ``fatal`` is
                True and default handling is enabled.
        """
        for eh in self._exceptionHandlers:
            eh(self, exception, fatal)
        if self._doDefaultExcpetionHandler:
            self._defaultExceptionHandler(exception, fatal)

    def __enter__(self):
        """Start the receiver thread and open the packet log if enabled.

        Returns:
            Bus: The running bus instance.
        """
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
        """Stop the bus and close any open packet log when leaving a context.

        Args:
            *exec_info: Standard context-manager exception information.

        Returns:
            None.
        """
        self.stop()
        # Close the log cleanly
        if self._log is not None:
            self._log.close()

    def __receive(self, canbus: can.ThreadSafeBus):
        """Run the background receive loop and notify riders of new packets.

        The loop polls the underlying CAN bus, wraps received CAN messages in
        ``DataPacket`` objects, optionally prints and logs them, and forwards
        each packet to every connected rider through ``_onPacket``.

        Args:
            canbus: Underlying thread-safe CAN bus used for reads.

        Returns:
            None.

        Raises:
            RuntimeError: If the underlying CAN bus reference becomes ``None``.
        """
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
        """Stop the bus, join the receiver thread, and shut down the CAN bus.

        Once stopped, the bus cannot be restarted.

        Returns:
            None.
        """
        # Mark that the bus is no longer running
        self.__running = False
        # Wait for the listener to cleanly exit
        self.__receiverThread.join()
        # Cleanly shut down the underlying CAN bus
        self.__canbus.shutdown()

    def addRider(self, rider):
        """Attach a rider and start forwarding received packets to it.

        The rider is connected to this bus through ``_connectBus`` and will be
        notified of future packets through ``_onPacket``.

        Args:
            rider: Rider object that implements the bus callback interface.

        Returns:
            None.

        Raises:
            RuntimeError: If the bus has already been stopped.
        """
        # Check if the bus is running
        if not self.__running:
            raise RuntimeError("The SensorBus has been stopped")
        # Add the rider
        rider._connectBus(self)
        self._riders.append(rider)

    def removeRider(self, rider):
        """Detach a rider and clear its bus reference when present.

        Args:
            rider: Rider object previously added to this bus.

        Returns:
            None.

        Raises:
            RuntimeError: If the bus has already been stopped.
        """
        # Checks if the bus is running
        if not self.__running:
            raise RuntimeError("The SensorBus has been stopped")
        # Removes the rider only if it exists
        if rider in self._riders:
            self._riders.remove(rider)
            rider._setBus(None)

    def send(self, message: DataPacket):
        """Send a packet on the CAN bus and log it when packet logging is enabled.

        Args:
            message: Packet to convert into a CAN message and transmit.

        Returns:
            None.

        Raises:
            Exception: Propagates through the configured exception handling path
                when sending fails or when the bus is no longer running.
        """
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
        """Print a debug line for a packet when packet printing is enabled.

        Args:
            packet: Packet object to display.
            msg: Prefix message shown before the packet contents.

        Returns:
            None.
        """
        if self._packetprint:
            print(f"{msg:10s} ", end="")
            print(packet)
