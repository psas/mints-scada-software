from nexus import Bus
from threading import Event, Thread
import time
import numpy as np

class AutoPoller():
    def __init__(self, bus: Bus, interval: float = 1):
        ''' Actual interval will be just slightly longer than given interval, and may not be perfectly conscistant '''
        self._minInterval: float = 0.001
        ''' The minimum interval between polls. This should be 0.001 on most systems, and is assumed to be so in the docs. '''
        self.__running: bool = False
        ''' (internal) If the poller is running. '''
        self._bus: Bus = bus
        ''' The bus that has the riders to poll '''
        self.__interval: float = interval if interval >= self._minInterval else 1  # in seconds
        ''' (internal) The time between polls '''

        self.__pollingThread: Thread = None
        ''' The thread that does the polling '''
        self.__stopEvent: Event = Event()
        ''' The event used to stop the polling '''

        self._nextPoll = 0
        ''' The time that the next poll should happen at '''
        self.statusListeners = {"start": None, "stop": None}
        ''' Listeners when the status of the autopoller changes '''

        # Stop the autopoller if there is an error on the bus
        def onBusException(bus, err, fatal):
            if fatal:
                self.stop()
        bus.addExceptionHandler(onBusException)

        # Track statistics about the accuracy of the autopoller interval
        self._lastPoll = 0
        ''' The time that the last poll occurred at '''
        self.avgBuffSize = 128
        ''' The size of the statistics averaging circular buffers. Changes only take effect after restarting the poller '''
        self._avgBuffIndex = 0
        ''' The index into the circular averaging buffers '''
        self.avgBuffFilled = False
        ''' If the buffer is full and averages are accurate '''
        self._avgTimeBuff = None
        ''' The buffer to hold measured intervals '''
        self._avgProcBuff = None
        ''' The buffer to hold measured polling time '''

    @property
    def running(self):
        ''' If the poller is running. '''
        return self.__running

    def getInterval(self) -> float:
        ''' Gets the desired interval between polls.
        
        Returns the interval in seconds '''
        return self.__interval

    def setInterval(self, s: float):
        ''' Sets the interval the autopoller polls at.
        Minimum is 1ms, a ValueError will be raised if you specify something too small.
        Changing self._minInterval changes the minimum allowable value.
        
        s: The desired time in seconds between polls'''
        if s >= self._minInterval: # max rate 1kHz
            self.__interval = s
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
        ''' Starts the autopoller '''
        # Reset statistics
        self.resetStats()
        # Set the desired time for the next poll 
        self._nextPoll = time.monotonic()
        # Notify anyone who cares we're about to start
        if self.statusListeners["start"] is not None:
            self.statusListeners["start"]()
        # Actually start
        self.__running = True
        self.__stopEvent.clear()
        self.__pollingThread = Thread(target=self.__pollingWorker)
        self.__pollingThread.start()
        print("Autopoller started")

    def stop(self):
        ''' Stops the autopoller. It can later be restarted, and you can still manually poll devices '''
        # Send the signal to stop running
        self.__running = False
        self.__stopEvent.set()
        # Let anyone who cares know we've just stopped
        if self.statusListeners["stop"] is not None:
            self.statusListeners["stop"]()
        print("Autopoller stopped")

    def resetStats(self):
        ''' Resets all statistics gathered about the polling process '''
        self._avgTimeBuff = np.zeros(self.avgBuffSize)
        self._avgProcBuff = np.zeros(self.avgBuffSize)
        self._avgBuffIndex = 0
        self.avgBuffFilled = False
        self._lastPoll = time.monotonic() - self.__interval

    def __pollingWorker(self):
        ''' Worker thread to poll the bus riders at the desired interval '''
        while self.__running:
            start = time.monotonic()
            # Poll everyone
            for d in self._bus._riders:
                d.poll()
            # Calculate poll time statistics
            proc = time.monotonic() - start
            self._avgProcBuff[self._avgBuffIndex] = proc
            # Calculate frequency statistics
            pt = start - self._lastPoll
            self._lastPoll = start
            self._avgTimeBuff[self._avgBuffIndex] = pt
            # Advance average pointer
            self._avgBuffIndex += 1
            if self._avgBuffIndex >= self.avgBuffSize:
                self.avgBuffFilled = True
                self._avgBuffIndex = 0
            # Schedule the next execution
            now = time.monotonic()
            self._nextPoll += self.__interval
            st = self._nextPoll - now
            if st < 0:
                print(f"Poller can't keep up! Running {-st}s behind. Consider picking a lower polling rate ")
                st = 0
            self.__stopEvent.wait(timeout=st)

    def getAveragePollTime(self) -> float:
        ''' Gets the average time in seconds each poll cycle takes.
        This should be close to, but will probably not exactly match the specified interval'''
        return np.average(self._avgTimeBuff)
    
    def getAvgProcTime(self) -> float:
        ''' Gets the average time in seconds it takes to send poll requests to all devices'''
        return np.average(self._avgProcBuff)