"""nexus/busrider.py

Base bus rider class for addressable Nexus bus devices.

This module defines the common runtime behavior shared by bus-backed device
objects. A ``BusRider`` tracks its bus address, software-visible device
identity, last update time, serial lookup state, and the packet/event flow
used by polling subclasses.

CAN message send format::

    Byte 0: sequence identifier (echoed back in the reply)
    Byte 1: command
    Bytes 2-7: arguments

CAN message receive format::

    Byte 0: sequence identifier (same as the outgoing message)
    Bytes 1-7: reply data

Commands ``0x00`` and ``0x01`` are ``GET_SERIAL_LOW`` and ``GET_SERIAL_HIGH``.
The ``simulated`` flag must never be changed after construction.
"""

from .datapacket import DataPacket
from .bus import Bus
from .buscommands import BusCommands
import threading


class BusRider:
    """Base class for devices that communicate over the Nexus bus.

    The base class stores device identity, tracks bus attachment state, handles
    common packet routing for the rider's address, and delegates device-specific
    decode and polling behavior to subclasses.
    """

    def __init__(self, id: int, device_id: str = "BusRider", simulated: bool = False):
        """Initialize the bus rider base state.

        Args:
            id: Hardware bus address of the remote device.
            device_id: Stable software identifier used by higher-level repo
                logic.
            simulated: Whether the device is simulated rather than backed by a
                live bus device.
        """
        # Hardware / bus address of the remote device
        self._id = id

        # Stable software identifier used everywhere in repo logic
        self.device_id = device_id

        # Optional display name for UI only
        self.display_name = device_id

        # The serial number of the sensor
        # TODO check this to help ensure that the correct sensor is at this address
        self._serial = None

        # The bus the rider rides on
        self._bus = None

        # Whether this device is simulated. DO NOT CHANGE after construction.
        self._simulated = simulated

        # Time of the last decoded reading.
        self.time = None

        # An event that is triggered when a new packet comes in for this sensor
        self._event = threading.Event()
        self._nextSequenceID = 0

    def _connectBus(self, bus: Bus):
        """Attach the rider to a bus and request its serial identifier.

        Live riders immediately send a ``READ_ID_LOW`` request after connecting
        so the remote device can report its serial data. Simulated riders skip
        that request.

        Args:
            bus: Bus instance that owns transport for this rider.
        """
        self._bus = bus
        if self._bus is not None and not self._simulated:
            # Get the ID of the sensor
            request = DataPacket(id=self._id, cmd=BusCommands.READ_ID_LOW)
            bus.send(request)

    def _onPacket(self, packet: DataPacket):
        """Handle an incoming packet addressed to this rider.

        Serial-identifier replies update ``_serial``. Other replies update the
        last packet time, delegate decoding to ``_decodePacket()``, and notify
        any waiters through the rider event.

        Args:
            packet: Incoming bus packet to inspect.
        """
        if packet is not None and packet.id == self._id:
            if packet.reply:
                if packet.cmd == BusCommands.READ_ID_LOW:
                    self._serial = packet.data
                else:
                    # Set the last updated time
                    self.time = packet.time
                    # Set the value
                    self._decodePacket(packet)
                    # Trigger anything waiting for this sensor
                    self._event.set()

    def _decodePacket(self, packet: DataPacket):
        """Decode a device-specific reply packet.

        Subclasses override this to translate reply data into device state.

        Args:
            packet: Reply packet for this rider.
        """
        pass

    def poll(self):
        """Issue a device-specific poll request.

        Subclasses override this to send the command sequence needed to refresh
        their state from the bus.
        """
        pass
