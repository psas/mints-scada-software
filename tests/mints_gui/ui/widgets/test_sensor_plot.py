import random
from time import perf_counter

import numpy as np
import pytest
from can import Notifier, ThreadSafeBus
from pyqtgraph import GraphicsLayoutWidget, PlotDataItem
from pyqtgraph.graphicsItems.PlotItem import PlotItem
from pytestqt.qtbot import QtBot

from mints_backend.datapacket import CAN_DATA_LEN, RESPONSE_MSG_ID, CANData, DataPacket
from mints_backend.devices import Sensor, SensorKind
from mints_gui.ui.widgets.sensor_plot import SensorPlot


@pytest.fixture()
def sensor(dev_bus: ThreadSafeBus, notifier: Notifier):
    sensor = Sensor(id=0x0, name="test0", kind=SensorKind.Temperature, bus=dev_bus)
    notifier.add_listener(sensor.handle_can_rx)
    yield sensor
    notifier.remove_listener(sensor.handle_can_rx)
    sensor.unsubscribe_all()


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
    sensor_plot = SensorPlot(sensor=sensor, update_period=0.01)
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

    sensor_plot_data_items: list[PlotDataItem] = sensor_plot.listDataItems()
    _, y = get_last_point_from_data_items(sensor_plot_data_items)

    assert y == sensor_plot.sensor.decode(sensor_plot_datapacket)


def test_shift_all_curves_left_sets_correct_position(sensor_plot: SensorPlot):
    """
    _shift_all_curves_left should translate the curves on the plot to the left correctly
    """
    for _ in range(5):
        sensor_plot._get_new_curve()
    now = perf_counter()
    sensor_plot._shift_all_curves_left(now)
    expected_x = -(now - sensor_plot.start_time)
    for curve in sensor_plot.curves:
        assert curve.pos().x() == pytest.approx(expected_x)


def test_get_new_curve(sensor_plot: SensorPlot):
    """
    _get_new_curve should append a new curve to the plots list of curves
    """
    prev_len = len(sensor_plot.curves)
    sensor_plot._get_new_curve()
    assert len(sensor_plot.curves) == prev_len + 1
    assert isinstance(sensor_plot.curves[-1], PlotDataItem)


def test_reset_data_preserve_last(sensor_plot: SensorPlot):
    """
    _reset_data_preserve_last should reset the plot data to an empty array
    but preserve the last data point
    """
    for i in range(5):
        sensor_plot.update_plot(i)

    prev_data = sensor_plot.data

    sensor_plot._reset_data_preserve_last()

    assert np.all(sensor_plot.data[0] == prev_data[-1])
    assert sensor_plot.data.shape == prev_data.shape


def test_trim_oldest_curves_removes_excess_curves(sensor_plot: SensorPlot):
    """
    _trim_oldest_chunks should remove curves from the beginning of self.curves
    until max_chunks remain
    """
    curves = [sensor_plot._get_new_curve() for _ in range(sensor_plot.max_chunks + 3)]

    sensor_plot._trim_oldest_curves()

    assert len(sensor_plot.curves) == sensor_plot.max_chunks
    assert sensor_plot.curves == curves[3:]


def test_trim_oldest_curves_noop_when_under_limit(sensor_plot: SensorPlot):
    """
    If curves are at or below max_chunks, nothing should be removed
    """
    curves = [sensor_plot._get_new_curve() for _ in range(sensor_plot.max_chunks)]

    sensor_plot._trim_oldest_curves()

    assert sensor_plot.curves == curves
