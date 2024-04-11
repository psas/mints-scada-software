from nexus import Bus
from threading import Timer
import time
import numpy as np

class AutoPoller():
    def __init__(self, bus: Bus, interval: float = 1, autoStart: bool = False):
        ''' Actual interval will be just slightly longer than given interval, and may not be perfectly conscistant '''
        self._minInterval = 0.001
        self.running: bool = False
        self._bus: Bus = bus
        self.__interval: float = interval if interval >= self._minInterval else 1  # in seconds

        # self.__flag = Event()
        self.__timer: Timer = None
        # self.__lastStep = 0

        self._nextPoll = 0
        self.statusListeners = {"start": None, "stop": None}
        self.onPoll = []

        def onBusException(bus, e, f):
            if f:
                self.stop()
        bus.addExceptionHandler(onBusException)

        self._lastPoll = 0
        self._avgBuffSize = 128
        ''' Changes only take effect after restarting the poller '''
        self._avgBuffIndex = 0
        self._avgBuffFilled = False
        self._avgTimeBuff = None
        self._avgProcBuff = None

        if(autoStart):
            self.start()

        print("Done set up")

    def getInterval(self):
        return self.__interval

    def setInterval(self, new):
        if new >= self._minInterval: # max rate 1kHz
            self.__interval = new
            self.resetStats()
        else:
            raise ValueError("Interval too small")

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
        # self._buffavg = np.zeros(self._buffSize)
        self.resetStats()
        self._nextPoll = time.monotonic()
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

    def resetStats(self):
        self._avgTimeBuff = np.zeros(self._avgBuffSize)
        self._avgProcBuff = np.zeros(self._avgBuffSize)
        self._avgBuffIndex = 0
        self._avgBuffFilled = False
        self._lastPoll = time.monotonic() - self.__interval

    def __runStep(self):
        if self.running:
            # Schedule the next execution
            now = time.monotonic()
            self._nextPoll += self.__interval
            st = self._nextPoll - now
            if st < 0:
                st += 0
            self.__timer = Timer(st, self.__runStep)
            self.__timer.start()
            # Gather data for statistics
            # Poll everyone
            # self.__poll()

            # Calculate statistics
            proc = time.monotonic() - now
            pt = now - self._lastPoll
            self._lastPoll = now
            self._avgTimeBuff[self._avgBuffIndex] = pt
            self._avgProcBuff[self._avgBuffIndex] = proc
            self._avgBuffIndex += 1
            if self._avgBuffIndex >= self._avgBuffSize:
                self._avgBuffFilled = True
                self._avgBuffIndex = 0
            for f in self.onPoll:
                f(self)

    def __poll(self):
        for d in self._bus._riders:
            d.poll()

    def getAveragePollTime(self):
        return np.average(self._avgTimeBuff)
    
    def getAvgProcTime(self):
        return np.average(self._avgProcBuff)