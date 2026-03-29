from __future__ import annotations

from pathlib import Path


SOURCE = Path(__file__).resolve().parents[2] / "gui" / "controller_window.py"


def test_controller_window_creates_live_telemetry_poller_only_for_live_mode() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert "LiveTelemetryPoller" in text
    assert "self.live_telemetry_poller = None if self.playback_mode else LiveTelemetryPoller(self.autopoller)" in text


def test_controller_window_starts_and_stops_live_telemetry_poller() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert "self.live_telemetry_poller.start()" in text
    assert "poller.close()" in text
