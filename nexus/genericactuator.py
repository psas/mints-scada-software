"""nexus/genericactuator.py

Generic actuator primitive built on the Nexus sensor packet model.

This module provides a generic actuator implementation that reuses
``GenericSensor`` transport and listener behavior while adding WRITE_VALUE
handling for actuator state updates and simulated-device replies.
"""

from .datapacket import DataPacket
from .buscommands import BusCommands
from .genericsensor import GenericSensor
import struct


class GenericActuator(GenericSensor):
    """Represent a generic bus-connected actuator with cached state.

    The actuator inherits the base packet decoding and listener behavior from
    ``GenericSensor`` and adds WRITE_VALUE support for outbound set commands and
    simulated inbound acknowledgements.

    Args:
        id: Bus device identifier used in packets for this actuator.
        device_id: Human-readable device name exposed to higher layers.
        simulated: Whether the actuator should emulate hardware replies when it
            receives matching non-reply packets.
    """

    def __init__(
        self, id: int, device_id: str = "GenericActuator", simulated: bool = False
    ):
        """Initialize the actuator and its cached boolean-like value.

        Args:
            id: Bus device identifier used in packets for this actuator.
            device_id: Human-readable device name exposed to higher layers.
            simulated: Whether the actuator should emulate hardware replies.
        """
        super().__init__(id=id, device_id=device_id, simulated=simulated)
        self.value = False

    def set(self, state: bool | int):
        """Cache a new actuator state and send a WRITE_VALUE packet.

        Args:
            state: Actuator value to cache locally and pack into the outgoing
                bus command.
        """
        # Update the state
        self.value = state
        # Send the command to change
        p = DataPacket(self._id, cmd=BusCommands.WRITE_VALUE, data=self._packValue())
        self._bus.send(p)

    def _decodePacket(self, packet: DataPacket):
        """Decode actuator WRITE_VALUE packets before falling back to the parent.

        For non-error WRITE_VALUE packets, this updates ``value`` and ``aux``
        from the packed payload. All other packets are delegated to
        ``GenericSensor._decodePacket``.

        Args:
            packet: Incoming packet addressed to this device.
        """
        if not packet.err:
            # Set value command
            if packet.cmd == BusCommands.WRITE_VALUE:
                self.value, self.aux = struct.unpack(self.STRUCT_FORMAT, packet.data)
                return
        super()._decodePacket(packet=packet)

    def _onPacket(self, packet: DataPacket):
        """Handle incoming packets for this actuator and simulated reply flow.

        When the packet targets this actuator and the actuator is simulated, a
        non-reply WRITE_VALUE packet updates the cached state, sends a reply
        packet with the repacked value, logs the reply through the bus debug
        path, and notifies listeners. All other matching packets fall back to
        the inherited ``GenericSensor`` handling.

        Args:
            packet: Incoming packet to inspect.
        """
        if packet is not None and packet.id == self._id:
            # Handle the set command
            if not packet.reply and self._simulated:
                if packet.cmd == BusCommands.WRITE_VALUE:
                    # Actually update the values
                    self.value, self.aux = struct.unpack(
                        self.STRUCT_FORMAT, packet.data
                    )
                    # Send a reply with the current value of the actuator.
                    # Must be repacked to ensure any unpacking errors are included.
                    reply = packet.getReply(self._packValue())
                    self._bus.send(reply)
                    self._bus.printDbgPacket(reply, "Sent reply")
                    # Notify anyone who cares, then don't go to the parent's onPacket
                    self.updateListeners()
                    return
            # Call onPacket from GenericSensor if we don't have anything special to do with it
            super()._onPacket(packet=packet)

    def readSensor(self):
        """Do nothing for generic actuators without autonomous sensor reads.

        Returns:
            None.
        """
        pass

    def setActuator(self):
        """Provide a no-op hardware hook for subclasses or real implementations.

        Returns:
            None.
        """
        pass
