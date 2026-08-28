import random

import pytest
from can import Notifier, ThreadSafeBus
from pyqtgraph import GraphicsLayoutWidget, PlotDataItem
from pyqtgraph.graphicsItems.PlotItem import PlotItem
from pytestqt.qtbot import QtBot

from mints_backend.datapacket import CAN_DATA_LEN, RESPONSE_MSG_ID, CANData, DataPacket
from mints_backend.device_manager import Sensor
from mints_backend.models import SensorKind
from mints_gui.ui.widgets.sensor_plot import SensorPlot


@pytest.fixture()
def sensor(dev_bus: ThreadSafeBus, notifier: Notifier):
    sensor = Sensor(id=0x0, name="test0", kind=SensorKind.Temperature, bus=dev_bus)
    notifier.add_listener(sensor.handle_can_rx)
    yield sensor
    notifier.remove_listener(sensor.handle_can_rx)
    sensor.unsubscribe()


@pytest.fixture()
def graphics_layout_widget(qtbot: QtBot):
    widget = GraphicsLayoutWidget()
    yield widget


@pytest.fixture()
def plot_item(graphics_layout_widget: GraphicsLayoutWidget):
    plot = graphics_layout_widget.addPlot()
    yield plot
    graphics_layout_widget.removeItem(plot)


@pytest.fixture()
def sensor_plot(qtbot: QtBot, sensor: Sensor, plot_item: PlotItem):
    sensor_plot = SensorPlot(sensor=sensor, plot=plot_item, update_period=0.01)
    yield sensor_plot


@pytest.fixture()
def sensor_plot_can_data():
    rand_bytes = random.randbytes(CAN_DATA_LEN)
    can_data = CANData(cmd=None, bytes=bytearray(rand_bytes))
    yield can_data


@pytest.fixture()
def sensor_plot_datapacket(sensor_plot_can_data: CANData, sensor_plot: SensorPlot):
    arbitration_id = RESPONSE_MSG_ID | sensor_plot.sensor.id
    datapacket = DataPacket(id=arbitration_id, is_err=False, data=sensor_plot_can_data)
    yield datapacket


def get_last_point_from_data_items(
    sensor_plot_data_items: list[PlotDataItem],
) -> tuple[int, int]:
    assert len(sensor_plot_data_items) > 0, "Expected plot data items but found none"

    last_data_item: PlotDataItem = sensor_plot_data_items[-1]
    data = last_data_item.getData()
    last_point = data[-1]

    assert last_point is not None, "Expected point but found none"

    return (last_point[0], last_point[1])


@pytest.mark.parametrize("repeat", range(3))
def test_plot_data_updated_from_subscription(
    sensor_plot: SensorPlot,
    sensor_plot_datapacket: DataPacket,
    test_bus: ThreadSafeBus,
    qtbot: QtBot,
    repeat,
):
    """
    The plot's data should update from the data returned by the sensors subscription
    Repeats 3 times with random byte values
    """
    with qtbot.waitSignal(
        sensor_plot.sensor.sig_value_received, timeout=100
    ) as _blocker:
        test_bus.send(sensor_plot_datapacket.to_can_message())

    sensor_plot_data_items: list[PlotDataItem] = sensor_plot.plot.listDataItems()
    _, y = get_last_point_from_data_items(sensor_plot_data_items)

    assert y == sensor_plot.sensor.decode(sensor_plot_datapacket)
