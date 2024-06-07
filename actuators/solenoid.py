from nexus import GenericActuator

class Solenoid(GenericActuator):
    def __init__(self, id: int, name: str = "Solenoid", openPos: bool = True, simulated: bool = False):
        super().__init__(id=id, name=name, simulated=simulated)
        self.openPos = openPos

    def setOpen(self, state: bool):
        self.set(state=state if self.openPos else not state)

    def open(self):
        ''' Opens the solenoid value '''
        self.setOpen(True)

    def close(self):
        ''' Closes the solenoid value '''
        self.setOpen(False)