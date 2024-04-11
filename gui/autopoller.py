from nexus import Bus
from threading import Event, Thread, Timer
import time

class AutoPoller():
    def __init__(self, bus: Bus, interval: float = 1, autoStart: bool = False):
        ''' Actual interval will be just slightly longer than given interval, and may not be perfectly conscistant '''
        self.running: bool = False
        self._bus: Bus = bus
        self._interval: float = interval # in seconds

        # self.__flag = Event()
        self.__timer: Timer = None
        # self.__lastStep = 0

        self.statusListeners = {"start": None, "stop": None}

        def onBusException(bus, e, f):
            if f:
                self.stop()
        bus.addExceptionHandler(onBusException)

        if(autoStart):
            self.start()

    def __enter__(self):
        ''' Enter a with block '''
        self.start()
        return self

    def __exit__(self, *exec_info):
        ''' Exit a with block '''
        self.stop()

    def start(self):
        self.running = True
        if self.statusListeners["start"] is not None:
            self.statusListeners["start"]()
        self.__runStep()
        print("Autopoller started")

    def stop(self):
        self.__timer.cancel()
        self.running = False
        if self.statusListeners["stop"] is not None:
            self.statusListeners["stop"]()
        print("Autopoller stopped")

    def __runStep(self):
        if self.running:
            self.__timer = Timer(self._interval, self.__runStep)
            self.__timer.start()
            self.__poll()
        # nextTime = self.__lastStep + self._interval
        # delay = max(nextTime - time.monotonic(), 0)
        # self.__lastStep = time.monotonic()
        # self.__timer = Timer(delay, self.__runStep).start()

    def __poll(self):
        for d in self._bus._riders:
            d.poll()