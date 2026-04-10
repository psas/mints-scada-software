# gui/live_telemetry_poller.py

"""Compatibility wrapper for live telemetry polling lifecycle.

This module keeps the existing GUI autopoller usable from the newer live graph
and controller paths without redesigning the polling stack. It exposes a small
lifecycle object that can start, stop, and query a best-effort running state
from legacy autopoller implementations with slightly different method names.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class LiveTelemetryPoller:
    """Adapt an existing autopoller object to a small live-mode lifecycle API.

    The wrapper is intentionally thin. It is used by the live controller/graph
    path to start polling when the window is created, stop polling when the
    window closes, and tolerate older autopoller objects that expose different
    start, stop, or running-state names.

    Attributes:
        START_METHODS: Supported start method names checked in order.
        STOP_METHODS: Supported stop method names checked in order.
        STATE_ATTRS: Supported running-state attribute or zero-argument method
            names checked in order.
    """

    START_METHODS = ("start", "start_polling", "enable", "resume")
    STOP_METHODS = ("stop", "stop_polling", "disable", "pause")
    STATE_ATTRS = ("running", "is_running", "enabled")

    def __init__(self, autopoller: Any | None, *, enabled: bool = True) -> None:
        """Initialize the lifecycle wrapper around an autopoller object.

        Args:
            autopoller: Existing autopoller-like object to wrap. It may expose
                any supported start/stop/state names.
            enabled: Whether this wrapper should actively manage the autopoller.
                The wrapper is forced disabled when ``autopoller`` is None.
        """
        self._autopoller = autopoller
        self._enabled = bool(enabled) and autopoller is not None
        self._running = False

    @property
    def enabled(self) -> bool:
        """Return whether lifecycle management is enabled for this wrapper.

        Returns:
            True when the wrapper is allowed to start and stop the underlying
            autopoller.
        """
        return self._enabled

    @property
    def running(self) -> bool:
        """Return the current running state for the wrapped autopoller.

        This prefers an externally reported state from the wrapped autopoller
        when one can be read. If no compatible state attribute or method is
        available, it falls back to the wrapper's internal lifecycle flag.

        Returns:
            The best available running-state value.
        """
        state = self._read_external_state()
        return self._running if state is None else state

    @property
    def autopoller(self) -> Any | None:
        """Return the wrapped autopoller object.

        Returns:
            The underlying autopoller-like object, or None when no autopoller
            was supplied.
        """
        return self._autopoller

    def start(self) -> bool:
        """Start the wrapped autopoller through the first supported start method.

        Returns:
            False when polling is disabled, no autopoller is available, or the
            selected start method explicitly returns False. Otherwise returns
            True after invoking the start method.

        Raises:
            AttributeError: If polling is enabled but the wrapped autopoller
                does not expose any supported start method.
        """
        if not self._enabled:
            log.info("[LiveTelemetryPoller] start skipped: disabled or no autopoller")
            self._running = False
            return False

        method = self._resolve_method(self.START_METHODS)
        if method is None:
            raise AttributeError(
                "autopoller does not expose a supported start method "
                f"{self.START_METHODS}"
            )

        result = method()
        self._running = True
        log.info(
            "[LiveTelemetryPoller] started via %s",
            getattr(method, "__name__", "<callable>"),
        )
        return False if result is False else True

    def stop(self) -> bool:
        """Stop the wrapped autopoller through the first supported stop method.

        Returns:
            False when polling is disabled, when no compatible stop method is
            available, or when the selected stop method explicitly returns
            False. Otherwise returns True after invoking the stop method.
        """
        if not self._enabled:
            self._running = False
            return False

        method = self._resolve_method(self.STOP_METHODS)
        if method is None:
            log.info("[LiveTelemetryPoller] stop skipped: no supported stop method")
            self._running = False
            return False

        result = method()
        self._running = False
        log.info(
            "[LiveTelemetryPoller] stopped via %s",
            getattr(method, "__name__", "<callable>"),
        )
        return False if result is False else True

    def close(self) -> None:
        """Stop polling during shutdown and log stop failures.

        Returns:
            None.
        """
        try:
            self.stop()
        except Exception:
            log.exception("[LiveTelemetryPoller] failed while stopping on close")

    def _resolve_method(self, names: tuple[str, ...]):
        """Return the first callable method exposed under the given names.

        Args:
            names: Candidate method names to check on the wrapped autopoller.

        Returns:
            The first callable attribute found, or None when no compatible
            method exists.
        """
        target = self._autopoller
        if target is None:
            return None
        for name in names:
            candidate = getattr(target, name, None)
            if callable(candidate):
                return candidate
        return None

    def _read_external_state(self) -> bool | None:
        """Read a best-effort running state from the wrapped autopoller.

        The wrapper checks known boolean attributes first, then zero-argument
        callables that return booleans. Callables that require positional
        arguments are ignored.

        Returns:
            The externally reported running state, or None when no compatible
            state source is available.
        """
        target = self._autopoller
        if target is None:
            return None
        for attr in self.STATE_ATTRS:
            value = getattr(target, attr, None)
            if isinstance(value, bool):
                return value
            if callable(value):
                try:
                    resolved = value()
                except TypeError:
                    continue
                if isinstance(resolved, bool):
                    return resolved
        return None
