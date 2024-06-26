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

class DataPacket():
    ''' Class representing a DataPacket to go on the can bus. 
    
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
    '''

    def __init__(self, message: can.Message):
        ''' Type hint for init. Creates a new DataPacket from a can message'''
        ...

    def __init__(self, id: int, seq: int = None, cmd: int = None, data: bytearray = None, reply: bool = False, err: bool = False, rsvd: bool = False):
        ''' Creates a new DataPacket from either an arbitration ID & data array or a can message '''
        self.time = time.time()
        if isinstance(id, int):
            # If we have an arbitration ID & data array
            self._prepare(aid=id, seq=seq, cmd=cmd, data=data, reply=reply, err=err, rsvd=rsvd)
        elif isinstance(id, can.Message):
            # If we have a can message
            if len(id.data) < 2:
                raise ValueError("Invalid packet length")
            self._prepare(aid=id.arbitration_id, seq=id.data[0], cmd=id.data[1], data=id.data[2:] if len(id.data) > 2 else [])
        else:
            # If we have neither, create a blank message
            self._prepare()

    def _prepare(self, aid: int = None, seq: int = None, cmd: int = None, data: bytearray = None, timestamp: float = None, reply: bool = None, err: bool = None, rsvd: bool = None):
        ''' Prepares a message. Used in init '''
        # TODO: This might break if values are 0, so change these "or"s to something better
        self.reply = reply or (aid >> 10) & 1 == 1 if aid is not None else False
        self.err =   err   or (aid >> 9)  & 1 == 1 if aid is not None else False
        self.rsvd =   rsvd   or (aid >> 8)  & 1 == 1 if aid is not None else False
        self.id = aid & 0xFF if aid is not None else 0
        self.seq = seq or random.randint(0x00, 0xFF)
        self.cmd = cmd or 0x00
        self.data = data or [0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
        self.timestamp = timestamp or time.time()
        # Make sure the data is the right length
        # while len(self.data) < 6:
        #     self.data.append(0x00)
        if len(self.data) > 6:
            self.data = self.data[0:5]

    def __str__(self):
        return f"{'E' if self.err == 1 else '.'}{self.rsvd:01b} {'<' if self.reply else '>'}{self.id:02X} #{self.seq:02X} !{self.cmd:02x}: {' '.join([f'{b:02X}' for b in self.data])}"

    def getLogString(self):
        return f"{time.strftime('%H:%M:%S', time.gmtime(self.timestamp))}.{int(((time.time()%1) * 1e6)):06d} {self}\n"

    def genCanMessage(self):
        ''' Sends the message on the given can bus '''
        # Validate (and fix if needed) the data before actually sending
        self.data = self.data or []
        while len(self.data) < 6:
            self.data.append(0x00)
        if len(self.data) > 6:
            self.data = self.data[0:6]
        # Put header and data in payload
        snddta = struct.pack("BB6B", self.seq, self.cmd, *self.data)
        msg = can.Message(arbitration_id= (self.reply&1) << 10 | (self.err&1) << 9 | (self.rsvd&1) << 8 | (self.id & 0xFF), data=snddta, is_extended_id=False)
        return msg
        # bus.send(msg, self)

    def getReply(self, data: bytearray = None, err: bool = False) -> DataPacket:
        ''' Creates a datapacket that is a reply to this packet '''
        if self.reply:
            raise ValueError("This DataPacket is already a reply, so you can't create a reply to it")
        return DataPacket(id=self.id, seq=self.seq, cmd=self.cmd, reply=True, data=data, err=err)

