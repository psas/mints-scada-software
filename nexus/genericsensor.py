# nexus/genericsensor.py

"""Generic sensor bus rider with request/reply decoding and value history.

This module defines a base sensor implementation for the Nexus bus layer. The
sensor can decode :contentReference[oaicite:0]{index=0}answer
READ_VALUE requests when running in simulated/local mode, and keep a rolling
time/value history for graphing or diagnostics.
"""

from typing import Callable
import struct
import random
from nexus import DataPacket, BusRider, BusCommands
import numpy as np
import logging


class GenericSensor(BusRider):
    """Represent a sensor that exchanges values through the standard bus protocol.

    The sensor inherits bus connectivity, packet waiting, and device identity
    behavior from ``BusRider``. It stores the most recent decoded value, an
    auxiliary 16-bit field, and a dynamically growing two-row history array of
    ``(time, logValue())`` samples captured from READ_VALUE replies.
    """

    STRUCT_FORMAT = "<IH"
    BASE_HISTORY_SIZE = 1000

    def __init__(
        self,
        id: int,
        device_id: str = "GenericSensor",
        simulated: bool = False,
        genVal: Callable = None,
    ):
        """Initialize the sensor state and optional simulated value generator.

        Args:
            id: Bus address used for request/reply traffic.
            device_id: Stable software identifier for the sensor.
            simulated: Whether the sensor should behave as a simulated local
                device instead of polling external hardware.
            genVal: Optional callable used to generate simulated sensor values.
                When provided, it replaces the default random generator.
        """
        super().__init__(id=id, device_id=device_id, simulated=simulated)
        self.log = logging.getLogger("genericsensor")
        # the value of the sensor, or None if there was an error. Must be an unsigned 4 byte int
        self.value = None
        # An auxiliary output from the sensor. Must be an unsigned 2 byte int.
        self.aux = None

        if genVal is not None:
            self.genVal = staticmethod(genVal)

        # Things that happen when packets come in
        # These will be called for every packet that comes in that is for this sensor.
        # The listener should check that any other conditions it needs are met.
        # These are called after the packet is processed and values or errors have been parsed.
        # The updated sensor is passed as the first argument.
        self._updateListeners = []
        self.history = np.zeros((2, self.BASE_HISTORY_SIZE))
        self.historyIndex = 0

    def genVal(self):
        """Generate a simulated sensor value.

        Returns:
            A random unsigned 32-bit integer suitable for ``self.value``.
        """
        return random.randint(0, (2**32) - 1)

    # TODO use the sequence number to determine what to do with an incoming packet
    def _decodePacket(self, packet: DataPacket):
        """Decode a reply packet and update cached sensor state.

        Successful READ_VALUE replies are unpacked into ``value`` and ``aux``.
        The decoded reading is then appended to the internal history buffer
        using the packet timestamp already stored on ``self.time``. Error
        packets clear ``value`` and log a sensor error.

        Args:
            packet: Reply packet addressed to this sensor.

        Returns:
            None.
        """
        if not packet.err:
            # TODO ID parsing should be done at the BusRider level, not here
            if packet.cmd == BusCommands.READ_ID_LOW:
                # TODO make the sent data actually useful
                pass
            elif packet.cmd == BusCommands.READ_ID_HIGH:
                # TODO make the sent data actually useful
                pass
            # Get value command
            elif packet.cmd == BusCommands.READ_VALUE:
                # Read the actual value
                self.value, self.aux = struct.unpack(self.STRUCT_FORMAT, packet.data)
                # Expand history if needed
                if self.historyIndex == np.shape(self.history)[1]:
                    self.history = np.append(
                        self.history, np.zeros((2, self.BASE_HISTORY_SIZE)), 1
                    )
                # Add it to the history
                self.history[:, self.historyIndex] = (self.time, self.logValue())
                self.historyIndex += 1
            else:
                # TODO figure out what should happen here
                pass
        else:
            self.log.error("Something bad :( The packet was an error")
            self.value = None

    def _onPacket(self, packet: DataPacket):
        """Handle inbound request and reply packets for this sensor address.

        Reply packets update the cached reading state, set the wait event used
        by synchronous reads, and detect failed CLAIM_ID responses. Non-reply
        packets are treated as requests directed at this sensor; in that case
        the sensor builds and sends an appropriate reply packet when possible.
        Registered update listeners are notified after handling any matching
        packet.

        Args:
            packet: Incoming packet observed on the bus.

        Returns:
            None.
        """
        if packet is not None and packet.id == self._id:
            if packet.reply:
                # Check if this was a failed ID claim and error if it was
                if packet.cmd == BusCommands.CLAIM_ID and packet.err:
                    self.log.fatal(
                        f"Nooooo something is wrong! A device reported this ID {self._id:02X} as taken!"
                    )
                else:
                    # Set the last updated time
                    self.time = packet.time
                    # Set the value
                    self._decodePacket(packet)
                    # Trigger anything waiting for this sensor
                    self._event.set()
            else:
                reply = packet.getReply()
                # Get ID command
                if packet.cmd == BusCommands.READ_ID_LOW:
                    # TODO make the sent data actually useful
                    reply.data = [0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
                elif packet.cmd == BusCommands.READ_ID_HIGH:
                    # TODO make the sent data actually useful
                    reply.data = [0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
                # Get value command
                elif packet.cmd == BusCommands.READ_VALUE:
                    self.readSensor()
                    if self.value is not None:
                        reply.data = self._packValue()
                    else:
                        reply.err = True
                elif packet.cmd == BusCommands.CLAIM_ID:
                    # Someone wanted this ID, that's fine. Don't need to say anything.
                    reply = None
                else:
                    reply.err = True
                if reply is not None:
                    self._bus.send(reply)
                    self._bus.printDbgPacket(reply, "Sent reply")

            self.updateListeners()

    def updateListeners(self):
        """Notify registered listeners after the sensor state changes.

        Each listener receives this sensor instance so it can inspect the
        updated reading, timestamps, and history state.

        Returns:
            None.
        """
        for listener in self._updateListeners:
            listener(self)

    def _packValue(self) -> bytearray:
        """Pack the current value and auxiliary field for a READ_VALUE reply.

        Returns:
            A packed payload matching ``STRUCT_FORMAT`` and suitable for
            ``DataPacket.data``.
        """
        return struct.pack(self.STRUCT_FORMAT, self.value, self.aux or 0)

    def addListener(self, packetListener: Callable):
        """Register a callback invoked after matching packets are processed.

        Args:
            packetListener: Callable that accepts the updated sensor instance.

        Returns:
            None.
        """
        self._updateListeners.append(packetListener)

    def poll(self):
        """Send a READ_VALUE request for a non-simulated sensor.

        Simulated sensors do not send bus traffic. Real sensors require an
        initialized bus connection; otherwise polling raises ``RuntimeError``.
        The method clears the wait event before sending the request packet.

        Returns:
            None.

        Raises:
            RuntimeError: If the sensor is not simulated and no bus has been
                connected.
        """
        # Only poll real sensors
        if self._simulated:
            return
        # Check if the canbus was initialized
        if self._bus is None:
            raise RuntimeError(
                "Please initialize the bus before trying to poll the sensor"
            )
        self._event.clear()
        # Ask the sensor to read
        p = DataPacket(id=self._id, cmd=BusCommands.READ_VALUE)
        self._bus.send(p)
        self._bus.printDbgPacket(p, "Sent poll")

    def readValue(self, timeout: float = None, onFail: Callable[..., None] = None):
        """Poll the sensor and wait for the next decoded value.

        Simulated sensors return the current cached value immediately. Real
        sensors send a READ_VALUE request, wait for ``_onPacket`` to set the
        event, and then return the most recently decoded value. When the wait
        times out, the optional failure callback is invoked and the method
        returns ``None``.

        Args:
            timeout: Maximum number of seconds to wait for a reply. ``None``
                waits indefinitely.
            onFail: Optional callback invoked when no reply is received before
                the timeout expires.

        Returns:
            The current sensor value after a successful read, or None when the
            wait times out.

        Raises:
            RuntimeError: If the sensor is not simulated and no bus has been
                connected.
        """
        # If the sensor is simulated, simply return the value
        if self._simulated:
            return self.value
        # Check if the canbus was initialized
        if self._bus is None:
            raise RuntimeError(
                "Please initialize the canbus before trying to poll the sensor"
            )
        # Ask the sensor to read
        self.poll()
        # Wait for the response
        if self._event.wait(timeout):
            # Return the response
            return self.value
        else:
            # No value was read in time
            if onFail is not None:
                onFail()
            return None

    def readSensor(self):
        """Refresh the local reading used to answer incoming READ_VALUE requests.

        The base implementation only updates simulated sensors by generating a
        new value through ``genVal``. Hardware-backed subclasses can override
        this method to read from a local device before replying to a poll
        request.

        Returns:
            None.
        """
        if self._simulated:
            self.value = self.genVal()
            self.log.info("My value is %s", self.value)

    def logValue(self):
        """Return the value recorded in the history buffer.

        Subclasses can override this to log a transformed representation while
        still keeping ``self.value`` as the raw decoded reading.

        Returns:
            The value stored for history logging.
        """
        return self.value
