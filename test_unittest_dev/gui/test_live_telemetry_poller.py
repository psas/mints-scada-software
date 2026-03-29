from __future__ import annotations

from gui.live_telemetry_poller import LiveTelemetryPoller


class _AutoPollerStartStop:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.running = False

    def start(self) -> None:
        self.started += 1
        self.running = True

    def stop(self) -> None:
        self.stopped += 1
        self.running = False


class _AutoPollerEnableDisable:
    def __init__(self) -> None:
        self.enabled = False
        self.enable_calls = 0
        self.disable_calls = 0

    def enable(self) -> None:
        self.enable_calls += 1
        self.enabled = True

    def disable(self) -> None:
        self.disable_calls += 1
        self.enabled = False


def test_live_telemetry_poller_starts_and_stops_existing_autopoller() -> None:
    target = _AutoPollerStartStop()
    poller = LiveTelemetryPoller(target)

    assert poller.enabled is True
    assert poller.running is False

    assert poller.start() is True
    assert target.started == 1
    assert poller.running is True

    assert poller.stop() is True
    assert target.stopped == 1
    assert poller.running is False


def test_live_telemetry_poller_supports_enable_disable_style_apis() -> None:
    target = _AutoPollerEnableDisable()
    poller = LiveTelemetryPoller(target)

    assert poller.start() is True
    assert target.enable_calls == 1
    assert poller.running is True

    assert poller.stop() is True
    assert target.disable_calls == 1
    assert poller.running is False


def test_live_telemetry_poller_is_noop_when_disabled() -> None:
    target = _AutoPollerStartStop()
    poller = LiveTelemetryPoller(target, enabled=False)

    assert poller.start() is False
    assert target.started == 0
    assert poller.running is False
