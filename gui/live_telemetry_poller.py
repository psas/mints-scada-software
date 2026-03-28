from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class LiveTelemetryPoller:
    """Thin adapter that defaults live telemetry pulling on top of the existing autopoller.

    Commit 4 intentionally does not redesign the polling stack. Instead it wraps the
    already-available autopoller object and gives the live graph/provider path a small,
    explicit lifecycle object:

    - live mode only
    - starts automatically when the controller window is created
    - stops when the controller window closes
    - best-effort compatible with existing autopoller method names

    Supported start method names:
      start, start_polling, enable, resume

    Supported stop method names:
      stop, stop_polling, disable, pause

    Supported state attribute names:
      running, is_running, enabled
    """

    START_METHODS = ("start", "start_polling", "enable", "resume")
    STOP_METHODS = ("stop", "stop_polling", "disable", "pause")
    STATE_ATTRS = ("running", "is_running", "enabled")

    def __init__(self, autopoller: Any | None, *, enabled: bool = True) -> None:
        self._autopoller = autopoller
        self._enabled = bool(enabled) and autopoller is not None
        self._running = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def running(self) -> bool:
        state = self._read_external_state()
        return self._running if state is None else state

    @property
    def autopoller(self) -> Any | None:
        return self._autopoller

    def start(self) -> bool:
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
        log.info("[LiveTelemetryPoller] started via %s", getattr(method, "__name__", "<callable>"))
        return False if result is False else True

    def stop(self) -> bool:
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
        log.info("[LiveTelemetryPoller] stopped via %s", getattr(method, "__name__", "<callable>"))
        return False if result is False else True

    def close(self) -> None:
        try:
            self.stop()
        except Exception:
            log.exception("[LiveTelemetryPoller] failed while stopping on close")

    def _resolve_method(self, names: tuple[str, ...]):
        target = self._autopoller
        if target is None:
            return None
        for name in names:
            candidate = getattr(target, name, None)
            if callable(candidate):
                return candidate
        return None

    def _read_external_state(self) -> bool | None:
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
