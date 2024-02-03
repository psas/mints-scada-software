import can

# ID bits
# [10]  reply 0=to id, 1=from id
# [9]   error
# [8]   reserved
# [7:0] Device ID

# Data is an 8 byte string

class DataPacket():
    ''' Class representing a DataPacket to go on the can bus. 
    
    self.reply is the reply bit
    self.err   is the error bit
    self.res   are the reserved bits from the ID
    self.id    is the address of the message
    self.data  is the array of 8 bytes of data 
    
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

    def __init__(self, id: int, data: bytearray = None, reply: bool = False, err: bool = False, res: bool = False):
        ''' Creates a new DataPacket from either an arbitration ID & data array or a can message '''
        if isinstance(id, int):
            # If we have an arbitration ID & data array
            self._prepare(id, data, reply, err, res)
        elif isinstance(id, can.Message):
            # If we have a can message
            self._prepare(id.arbitration_id, id.data)
        else:
            # If we have neither, create a blank message
            self._prepare()

    def _prepare(self, aid: int = None, data: bytearray = None, reply: bool = None, err: bool = None, res: bool = None):
        ''' Prepares a message. Used in init '''
        self.reply = reply or (aid >> 10) & 1 == 1 if aid is not None else False
        self.err =   err   or (aid >> 9)  & 1 == 1 if aid is not None else False
        self.res =   res   or (aid >> 8)  & 1 == 1 if aid is not None else False
        self.id = aid & 0xFF if aid is not None else 0
        self.data = data or [0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]

    def print(self):
        ''' Prints a message to the terminal '''
        print(f"{'<' if self.reply else '>'}{'E' if self.err == 1 else '.'}{self.res:01b} {self.id:02X}: {' '.join([f'{b:02X}' for b in self.data])}")

    def send(self, bus):
        ''' Sends the message on the given can bus '''
        msg = can.Message(arbitration_id= (self.reply&1) << 10 | (self.err&1) << 9 | (self.res&1) << 8 | (self.id & 0xFF), data=self.data, is_extended_id=True)
        bus.send(msg)