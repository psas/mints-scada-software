from nexus import GenericActuator

class Solenoid(GenericActuator):
    def __init__(self, id: int, name: str = "Solenoid", inverted: bool = False, simulated: bool = False):
        super().__init__(id=id, name=name, simulated=simulated)
        self.inverted = inverted

    def setOpen(self, state: bool):
        self.set(state=state if not self.inverted else not state)

    def open(self):
        ''' Opens the solenoid value '''
        self.setOpen(True)

    def close(self):
        ''' Closes the solenoid value '''
        self.setOpen(False)

    @property
    def state(self):
        ''' The state of the solenoid valve '''
        return self.value if not self.inverted else not self.value