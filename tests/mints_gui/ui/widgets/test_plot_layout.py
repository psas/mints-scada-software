import pytest
from pytestqt.qtbot import QtBot

from mints_backend.device_manager import DeviceManager
from mints_gui.ui.widgets.plot_layout import PlotLayout


@pytest.fixture
def plot_layout(qtbot: QtBot, device_manager: DeviceManager):
    plot_layout = PlotLayout(device_manager.device_registry)
    yield plot_layout


def test_init(plot_layout: PlotLayout):
    assert plot_layout.num_graphs > 0
    assert len(plot_layout.plots) > 0
