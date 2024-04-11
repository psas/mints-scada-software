from nexus import Bus
from threading import Timer
import time
import numpy as np

class AutoPoller():
    def __init__(self, bus: Bus, interval: float = 1, autoStart: bool = False):
        ''' Actual interval will be just slightly longer than given interval, and may not be perfectly conscistant '''
        self.running: bool = False
        self._bus: Bus = bus
        self.interval: float = interval # in seconds

        # self.__flag = Event()
        self.__timer: Timer = None
        # self.__lastStep = 0

        self.statusListeners = {"start": None, "stop": None}
        self.onPoll = []

        def onBusException(bus, e, f):
            if f:
                self.stop()
        bus.addExceptionHandler(onBusException)

        if(autoStart):
            self.start()

        self._lastPoll = 0
        self._statAverage = 16
        ''' Changes only take effect after restarting the poller '''
        self._buffavg = None
        self._buffindex = 0

    @property
    def interval(self):
        return self.__interval

    @interval.setter
    def interval(self, new):
        if new > 0.001: # max rate 1kHz
            self.__interval = new

    def __enter__(self):
        ''' Enter a with block '''
        self.start()
        return self

    def __exit__(self, *exec_info):
        ''' Exit a with block '''
        self.stop()

    def start(self):
        self.running = True
        # Set up statistics
        self._buffavg = np.zeros(self._statAverage)
        self._buffindex = 0
        # Notify anyone who cares we're about to start
        if self.statusListeners["start"] is not None:
            self.statusListeners["start"]()
        # Actually start
        self.__runStep()
        print("Autopoller started")

    def stop(self):
        self.running = False
        self.__timer.cancel()
        if self.statusListeners["stop"] is not None:
            self.statusListeners["stop"]()
        print("Autopoller stopped")

    def __runStep(self):
        if self.running:
            # Schedule the next execution
            self.__timer = Timer(self.__interval, self.__runStep)
            self.__timer.start()
            # Gather data for statistics
            now = time.monotonic()
            # Poll everyone
            self.__poll()
            # Calculate statistics
            pt = now - self._lastPoll
            self._lastPoll = now
            self._buffindex = ((self._buffindex + 1) % self._statAverage)
            self._buffavg[self._buffindex] = pt
            for f in self.onPoll:
                f(self)

    def __poll(self):
        for d in self._bus._riders:
            d.poll()

    def getAveragePollTime(self):
        return np.average(self._buffavg)