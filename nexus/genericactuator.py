from nexus import GenericSensor

class GenericActuator(GenericSensor):
    def __init__(self, id: int, simulated: bool = False):
        super().__init__(id=id, simulated=simulated)



    def readSensor(self):
        ''' This won't change unless requested to, so we don't have to do anything here '''
        pass

    def setActuator(self):
        ''' This would actually set the output if this was a real sensor '''
        