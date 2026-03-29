from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
qt = pytest.importorskip("PyQt5")

from gui.graph_data import GraphSample
from gui.graph_provider import InMemoryGraphDataProvider
from gui.view_graph import GraphView


def test_graph_view_uses_provider_window_for_playback_queries(qtbot):
    provider = InMemoryGraphDataProvider()
    provider.ingest_samples([
        GraphSample(timestamp=5.0, channel_key="pt-1", value=10.0, source="playback"),
        GraphSample(timestamp=12.0, channel_key="pt-1", value=20.0, source="playback"),
    ])
    provider.set_time_window(start_ts=0.0, end_ts=10.0)

    view = GraphView()
    qtbot.addWidget(view)
    view.attach_graph_provider(provider)
    view.duration = 60

    class Sensor:
        device_id = "pt-1"
        display_name = "PT-1"
        history = None

    hist = view._extract_history(Sensor())
    assert hist is not None
    assert hist.shape[1] == 1
    assert hist[0, 0] == pytest.approx(5.0)
    assert hist[1, 0] == pytest.approx(10.0)
