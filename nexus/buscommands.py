# nexus/buscommands.py

"""Canonical bus command identifiers used by Nexus packet helpers."""


class BusCommands():
    """Namespace for low-level bus command byte values.

    The constants in this class define the command identifiers used when
    building or decoding Nexus bus packets for device identification, value
    reads, value writes, and ID claiming.
    """

    READ_ID_LOW  = 0x10
    READ_ID_HIGH = 0x11
    READ_VALUE   = 0x80
    WRITE_VALUE  = 0xC0
    CLAIM_ID     = 0x0F
