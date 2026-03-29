from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
QApplication = QtWidgets.QApplication

from gui.live_graph_provider import LiveGraphDataProvider
from gui.view_graph import GraphView


class _Device:
    def __init__(self, device_id: str, display_name: str):
        self.device_id = device_id
        self.display_name = display_name


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_graph_view_uses_provider_when_device_has_no_history():
    _app()
    provider = LiveGraphDataProvider()
    provider.ingest_state_snapshot({
        "wall_time": "2026-03-27T12:00:00Z",
        "device_registry": {"devices": [{"id": "pt-1", "name": "PT 1"}]},
        "device_runtime": {
            "by_id": {
                "pt-1": {"runtime_value": 11.0, "runtime_time": 100.0},
            }
        },
    })

    graph = GraphView()
    graph.attach_graph_provider(provider)
    graph.add_device(_Device("pt-1", "PT 1"), graphed=True)

    hist = graph._extract_history(graph.sensors[0])
    assert hist is not None
    assert hist.shape[0] >= 2
    assert float(hist[1][-1]) == 11.0


def test_graph_view_prefers_sensor_history_when_present():
    _app()

    class _HistoryDevice(_Device):
        def __init__(self):
            super().__init__("pt-2", "PT 2")
            self.history = [[1.0, 2.0], [3.0, 4.0]]

    graph = GraphView()
    graph.add_device(_HistoryDevice(), graphed=True)
    hist = graph._extract_history(graph.sensors[0])
    assert hist is not None
    assert float(hist[1][-1]) == 4.0
