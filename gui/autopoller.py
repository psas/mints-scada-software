"""gui/autopoller.py

Background bus polling for live device riders.

This module defines ``AutoPoller``, a thread-based polling loop that repeatedly
calls ``poll()`` on every rider registered on a ``nexus.Bus``. It also tracks
basic interval and processing-time statistics and exposes simple lifecycle
hooks for GUI listeners.
"""

from nexus import Bus, dbgutils
from threading import Event, Thread
import time
import numpy as np

import logging

log = logging.getLogger("autopoller")


class AutoPoller():
    """Poll bus riders on a fixed interval from a background thread.

    The poller iterates over ``bus._riders`` and calls ``poll()`` on each rider
    until stopped. It maintains rolling timing statistics for the measured poll
    interval and the time spent issuing polls, and it can notify listeners when
    the poller starts, stops, or changes interval.
    """

    CHANGE_INTERVAL_EVENT = "change_interval"
    START_EVENT = "start"
    STOP_EVENT = "stop"

    def __init__(self, bus: Bus, interval: float = 1, autostart=True):
        """Initialize the autopoller and register the bus exception handler.

        Args:
            bus: Bus whose riders will be polled by the worker thread.
            interval: Desired polling interval in seconds. Values below the
                minimum interval are replaced with the default interval of
                ``1`` second.
            autostart: Whether entering the context manager should start the
                poller automatically.
        """
        # Actual interval will be just slightly longer than the requested
        # interval, and may not be perfectly consistent.
        self._minInterval: float = 0.001
        # The minimum interval between polls.
        self.__running: bool = False
        # Internal running flag for the worker loop.
        self._bus: Bus = bus
        # The bus that owns the riders to poll.
        self.__interval: float = interval if interval >= self._minInterval else 1
        # Internal target time between polls, in seconds.
        self.__autostart = autostart
        # Whether entering the context manager should auto-start the poller.

        self.__pollingThread: Thread = None
        # The thread that runs the polling worker.
        self.__stopEvent: Event = Event()
        # Event used to wake and stop the polling worker.

        self._nextPoll = 0
        # Monotonic timestamp for the next scheduled poll.
        self.statusListeners = {
            self.START_EVENT: None,
            self.STOP_EVENT: None,
            self.CHANGE_INTERVAL_EVENT: None,
        }
        # Optional listeners notified when the poller lifecycle changes.

        # Stop the autopoller if there is an error on the bus.
        def onBusException(bus, err, fatal):
            """Stop the autopoller when a fatal bus error occurs.

            Args:
                bus: The bus instance that raised the exception.
                err: The exception that occurred.
                fatal: Whether the error is fatal to the bus.
            """
            if fatal:
                self.stop()

        bus.addExceptionHandler(onBusException)

        # Track statistics about the accuracy of the autopoller interval.
        self._lastPoll = 0
        # Monotonic timestamp of the last poll start.
        self.avgBuffSize = 128
        # Size of the circular averaging buffers.
        self._avgBuffIndex = 0
        # Current index into the circular averaging buffers.
        self.avgBuffFilled = False
        # Whether the circular averaging buffers have wrapped at least once.
        self._avgTimeBuff = None
        # Circular buffer of measured intervals between poll starts.
        self._avgProcBuff = None
        # Circular buffer of measured poll-processing durations.

    @property
    def running(self):
        """Return whether the polling loop is currently active.

        Returns:
            True when the background polling thread has been started and not
            yet stopped.
        """
        return self.__running

    def getInterval(self) -> float:
        """Return the configured interval between poll cycles.

        Returns:
            The requested interval in seconds.
        """
        return self.__interval

    def setInterval(self, s: float):
        """Set the interval between poll cycles and reset timing statistics.

        Args:
            s: Desired time in seconds between polls.

        Raises:
            ValueError: If ``s`` is smaller than the configured minimum
                interval.
        """
        log.info(f"Set interval to {s}")
        if s >= self._minInterval:  # max rate 1kHz
            self.__interval = s
            self.resetStats()
            if self.statusListeners[self.CHANGE_INTERVAL_EVENT] is not None:
                log.info("Updating listener")
                self.statusListeners[self.CHANGE_INTERVAL_EVENT]()
        else:
            raise ValueError("Interval too small")

    def setIntervalChangeListener(self, listener: callable):
        """Register the listener notified after interval changes.

        The listener is invoked immediately after registration when it is not
        ``None``, matching the existing behavior used by the GUI.

        Args:
            listener: Callback invoked with no arguments when the interval
                listener should refresh its state.
        """
        self.statusListeners[AutoPoller.CHANGE_INTERVAL_EVENT] = listener
        if self.statusListeners[self.CHANGE_INTERVAL_EVENT] is not None:
            self.statusListeners[self.CHANGE_INTERVAL_EVENT]()

    def __enter__(self):
        """Enter the context manager and optionally start polling.

        Returns:
            The current ``AutoPoller`` instance.
        """
        if self.__autostart:
            self.start()
        return self

    def __exit__(self, *exec_info):
        """Exit the context manager and stop polling.

        Args:
            *exec_info: Standard context-manager exception information, unused
                by this implementation.

        Returns:
            None.
        """
        self.stop()

    def start(self):
        """Start the polling worker if it is not already running.

        Starting resets the timing statistics, schedules the next poll based on
        the current monotonic clock, notifies the registered start listener, and
        launches the worker thread.
        """
        if not self.__running:
            # Reset statistics.
            self.resetStats()
            # Set the desired time for the next poll.
            self._nextPoll = time.monotonic()
            # Notify anyone who cares we're about to start.
            if self.statusListeners[self.START_EVENT] is not None:
                self.statusListeners[self.START_EVENT]()
            # Actually start.
            self.__running = True
            self.__stopEvent.clear()
            self.__pollingThread = Thread(target=self.__pollingWorker)
            self.__pollingThread.start()
            log.info("Autopoller started")

    def stop(self):
        """Stop the polling worker if it is running.

        This clears the running flag, signals the stop event used by the worker
        wait loop, and notifies the registered stop listener. Manual device
        polling outside the autopoller is unaffected.
        """
        # Send the signal to stop running.
        if self.__running:
            self.__running = False
            self.__stopEvent.set()
            # Let anyone who cares know we've just stopped.
            if self.statusListeners[self.STOP_EVENT] is not None:
                self.statusListeners[self.STOP_EVENT]()
            log.info("Autopoller stopped")

    def resetStats(self):
        """Reset the rolling timing statistics buffers.

        This recreates the interval and processing-time buffers, resets the
        circular index bookkeeping, and sets the previous poll timestamp so the
        next measured interval starts from the current configured interval.
        """
        self._avgTimeBuff = np.zeros(self.avgBuffSize)
        self._avgProcBuff = np.zeros(self.avgBuffSize)
        self._avgBuffIndex = 0
        self.avgBuffFilled = False
        self._lastPoll = time.monotonic() - self.__interval

    def __pollingWorker(self):
        """Run the polling loop until the stop event is set.

        Each cycle polls every rider on the bus, records measured timing
        statistics, advances the circular buffers, and then waits until the
        next scheduled poll time. When polling falls behind schedule, the loop
        logs a warning and immediately continues.
        """
        while self.__running:
            start = time.monotonic()
            # Poll everyone.
            for d in self._bus._riders:
                d.poll()
            # Calculate poll time statistics.
            proc = time.monotonic() - start
            self._avgProcBuff[self._avgBuffIndex] = proc
            # Calculate frequency statistics.
            pt = start - self._lastPoll
            self._lastPoll = start
            self._avgTimeBuff[self._avgBuffIndex] = pt
            # Advance average pointer.
            self._avgBuffIndex += 1
            if self._avgBuffIndex >= self.avgBuffSize:
                self.avgBuffFilled = True
                self._avgBuffIndex = 0
            # Schedule the next execution.
            now = time.monotonic()
            self._nextPoll += self.__interval
            st = self._nextPoll - now
            if st < 0:
                log.warn(
                    f"Poller can't keep up! Running {-st*1000:.1f}ms behind. "
                    "Consider picking a lower polling rate "
                )
                st = 0
            self.__stopEvent.wait(timeout=st)

    def getAveragePollTime(self) -> float:
        """Return the average measured interval between poll starts.

        Returns:
            The average time in seconds between the start of consecutive poll
            cycles across the current statistics buffer.
        """
        return np.average(self._avgTimeBuff)

    def getAvgProcTime(self) -> float:
        """Return the average time spent issuing poll requests.

        Returns:
            The average time in seconds spent polling all riders across the
            current statistics buffer.
        """
        return np.average(self._avgProcBuff)
