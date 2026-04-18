# nexus/datapacket.py

"""CAN packet wrapper used throughout the Nexus bus layer.

This module defines ``DataPacket``, a small convenience wrapper around the
project's 11-bit CAN packet format. The wrapper can be created either from raw
packet fields or from a ``python-can`` ``Message`` and exposes helpers for
legacy log formatting, reply construction, and conversion back into a CAN
message.
"""

# Keep your syntax highlighter happy when you return a DataPacket from a function in DataPacket
from __future__ import annotations

# Regular imports
import can
import time
import random
import struct

# ID bits
# [10]  reply 0=to id, 1=from id
# [9]   error
# [8]   reserved
# [7:0] Device ID

# The data field of the CAN messages:
#   First byte is the sequence number. It must be included in a reply so the sender knows this is the reply to that query.
#   Second byte is the command. It must be included in a reply so that other devices know what the reply is about.
#   The remaining 6 bytes are the payload data or command and arguments.


class DataPacket:
    """Represent one project CAN packet and its parsed header fields.

    A ``DataPacket`` stores the reply, error, reserved, device-id, sequence,
    command, and payload fields used by the project's CAN packet format. It can
    be constructed either from raw field values or by parsing an incoming
    ``can.Message``.

    self.reply is the reply bit
    self.err   is the error bit
    self.rsvd  in the reserved bits from the ID
    self.id    is the address of the message
    self.num   is the sequence number
    self.cmd   is the command
    self.data  is the array of 6 bytes of data

    The reply bit determines if the message is a reply to another message. This determines the meaning of the ID bit
        If the bit is 0, the id is the destination of the packet
        If the bit is 1, the id is the source of the packet
    This is intended to be used for a controller requesting data from a node using the node id with the reply bit set to 0.
    The node will then reply with the same id but the reply bit set to 1.
    This means the controller may have to listen to many IDs to receive the response.

    The error bit will be set if the device encountered a fatal error during processing

    Attributes:
        time: Creation time captured when the instance is initialized.
        reply: Whether the packet is marked as a reply.
        err: Whether the packet is marked as an error.
        rsvd: Reserved header bit from the arbitration ID.
        id: Eight-bit device ID from the packet header.
        seq: Sequence number stored in the first data byte.
        cmd: Command byte stored in the second data byte.
        data: Packet payload data stored after the sequence and command bytes.
        timestamp: Timestamp used for log formatting.
    """

    def __init__(self, message: can.Message):
        """Create a packet from a CAN message.

        Args:
            message: Incoming CAN message to parse.

        Returns:
            None.
        """
        ...

    def __init__(
        self,
        id: int,
        seq: int = None,
        cmd: int = None,
        data: bytearray = None,
        reply: bool = False,
        err: bool = False,
        rsvd: bool = False,
    ):
        """Create a packet from raw fields, a CAN message, or blank defaults.

        When ``id`` is an ``int``, the packet is initialized from the supplied
        header fields and payload values. When ``id`` is a ``can.Message``, the
        packet is parsed from that message's arbitration ID and first eight data
        bytes. Any other value produces a blank/default packet through
        ``_prepare()``.

        Args:
            id: Either an arbitration/device ID integer or a ``can.Message`` to
                parse.
            seq: Optional sequence number. A random byte is generated when not
                provided during raw-field construction.
            cmd: Optional command byte.
            data: Optional payload bytes stored after the sequence and command
                bytes.
            reply: Reply-bit override for raw-field construction.
            err: Error-bit override for raw-field construction.
            rsvd: Reserved-bit override for raw-field construction.

        Raises:
            ValueError: If a ``can.Message`` input contains fewer than two data
                bytes for the sequence and command fields.
        """
        self.time = time.time()
        if isinstance(id, int):
            # If we have an arbitration ID & data array
            self._prepare(
                aid=id, seq=seq, cmd=cmd, data=data, reply=reply, err=err, rsvd=rsvd
            )
        elif isinstance(id, can.Message):
            # If we have a can message
            if len(id.data) < 2:
                raise ValueError("Invalid packet length")
            self._prepare(
                aid=id.arbitration_id,
                seq=id.data[0],
                cmd=id.data[1],
                data=id.data[2:] if len(id.data) > 2 else [],
            )
        else:
            # If we have neither, create a blank message
            self._prepare()

    def _prepare(
        self,
        aid: int = None,
        seq: int = None,
        cmd: int = None,
        data: bytearray = None,
        timestamp: float = None,
        reply: bool = None,
        err: bool = None,
        rsvd: bool = None,
    ):
        """Populate packet fields from parsed values and default fallbacks.

        This method derives reply, error, reserved, and device-id fields from
        ``aid`` when available, applies explicit overrides for raw-field
        construction, assigns default sequence, command, and payload values, and
        bounds the stored payload length before the packet is used elsewhere.

        Args:
            aid: Raw arbitration ID to decode.
            seq: Parsed or requested sequence number.
            cmd: Parsed or requested command byte.
            data: Parsed or requested payload bytes.
            timestamp: Timestamp to store on the packet. The current time is
                used when omitted.
            reply: Explicit reply-bit override.
            err: Explicit error-bit override.
            rsvd: Explicit reserved-bit override.

        Returns:
            None.
        """
        # TODO: This might break if values are 0, so change these "or"s to something better
        self.reply = reply or (aid >> 10) & 1 == 1 if aid is not None else False
        self.err = err or (aid >> 9) & 1 == 1 if aid is not None else False
        self.rsvd = rsvd or (aid >> 8) & 1 == 1 if aid is not None else False
        self.id = aid & 0xFF if aid is not None else 0
        self.seq = seq or random.randint(0x00, 0xFF)
        self.cmd = cmd or 0x00
        self.data = data or [0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
        self.timestamp = timestamp or time.time()
        # Make sure the data is the right length
        # while len(self.data) < 6:
        #     self.data.append(0x00)
        if len(self.data) > 6:
            self.data = self.data[0:6]

    def __str__(self):
        """Return the legacy human-readable packet summary string.

        Returns:
            A compact string containing header flags, device ID, sequence,
            command, and payload bytes.
        """
        return f"{'E' if self.err == 1 else '.'}{self.rsvd:01b} {'<' if self.reply else '>'}{self.id:02X} #{self.seq:02X} !{self.cmd:02x}: {' '.join([f'{b:02X}' for b in self.data])}"

    def getLogString(self):
        """Build the legacy log line representation for the packet.

        Returns:
            A newline-terminated log string containing a formatted timestamp and
            the packet summary from ``__str__()``.
        """
        return f"{time.strftime('%H:%M:%S', time.gmtime(self.timestamp))}.{int(((time.time()%1) * 1e6)):06d} {self}\n"

    def genCanMessage(self):
        """Convert the packet back into a ``python-can`` message.

        The payload is padded or truncated so the packed CAN data always
        contains the sequence byte, command byte, and six payload bytes.

        Returns:
            A ``can.Message`` built from the packet's current header fields and
            payload data.
        """
        # Validate (and fix if needed) the data before actually sending
        self.data = self.data or []
        while len(self.data) < 6:
            self.data.append(0x00)
        if len(self.data) > 6:
            self.data = self.data[0:6]
        # Put header and data in payload
        snddta = struct.pack("BB6B", self.seq, self.cmd, *self.data)
        msg = can.Message(
            arbitration_id=(self.reply & 1) << 10
            | (self.err & 1) << 9
            | (self.rsvd & 1) << 8
            | (self.id & 0xFF),
            data=snddta,
            is_extended_id=False,
        )
        return msg
        # bus.send(msg, self)

    def getReply(self, data: bytearray = None, err: bool = False) -> DataPacket:
        """Build a reply packet that mirrors this packet's ID, sequence, and command.

        Args:
            data: Optional reply payload bytes.
            err: Whether the reply packet should set the error bit.

        Returns:
            A new ``DataPacket`` marked as a reply to this packet.

        Raises:
            ValueError: If this packet is already marked as a reply.
        """
        if self.reply:
            raise ValueError(
                "This DataPacket is already a reply, so you can't create a reply to it"
            )
        return DataPacket(
            id=self.id, seq=self.seq, cmd=self.cmd, reply=True, data=data, err=err
        )
