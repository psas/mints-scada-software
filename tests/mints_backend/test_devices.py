import threading

import can
import pytest
from pytestqt.qtbot import QtBot

from mints_backend.datapacket import CAN_DATA_LEN, RESPONSE_MSG_ID, CANData, DataPacket
from mints_backend.device_manager import BoardCfgListModel, DeviceManager
from mints_backend.devices import Device, Output, Sensor
from mints_backend.models import SensorKind


@pytest.fixture()
def event_bool():
    event = threading.Event()
    yield event
    event.clear()


@pytest.fixture()
def device(dev_bus: can.ThreadSafeBus):
    yield Device(id=0x0, name="TEST", bus=dev_bus)


@pytest.fixture()
def sensor(dev_bus: can.ThreadSafeBus, notifier: can.Notifier):
    sensor = Sensor(id=0x1, name="TEST0", kind=SensorKind.Temperature, bus=dev_bus)
    notifier.add_listener(sensor.handle_can_rx)
    yield sensor


@pytest.fixture()
def sensor_datapacket(sensor: Sensor):
    resp_id = RESPONSE_MSG_ID | sensor.id
    resp_data = CANData(None, bytearray(CAN_DATA_LEN))
    yield DataPacket(id=resp_id, is_err=False, data=resp_data)


@pytest.fixture()
def output(dev_bus: can.ThreadSafeBus, notifier: can.Notifier):
    output = Output(id=0x2, name="Test1", bus=dev_bus)
    notifier.add_listener(output.handle_can_rx)
    yield output


@pytest.fixture()
def output_datapacket(output: Output):
    resp_id = RESPONSE_MSG_ID | output.id
    resp_data = CANData(None, bytearray(CAN_DATA_LEN))
    yield DataPacket(id=resp_id, is_err=False, data=resp_data)


def test_sensor_init_success(sensor: Sensor):
    """
    Sensor devices should initialize successfully under normal conditions
    """
    assert sensor.id is not None
    assert sensor.name is not None
    assert isinstance(sensor.bus, can.ThreadSafeBus)


def test_output_init_success(output: Output):
    """
    Output devices should initialize successfully under normal conditions
    """
    assert output.id is not None
    assert output.name is not None
    assert isinstance(output.bus, can.ThreadSafeBus)


def test_sensor_subscribe_unsubscribe(sensor: Sensor, test_bus: can.ThreadSafeBus):
    """
    Sensors should send CAN messages when subscribed to, and shouldn't send messages when unsubscribed from
    """

    def test_fn(_args):
        return

    sensor.subscribe(test_fn, send_period=0.01)
    assert test_bus.recv(timeout=0.01) is not None
    sensor.unsubscribe(test_fn)
    assert test_bus.recv(timeout=0.02) is None


def test_sensor_unsubscribe_all(sensor: Sensor, test_bus: can.ThreadSafeBus):
    """
    unsubscribe_all should unsubscribe all slot functions from a sensor
    """

    def test_fn1(_args):
        return

    def test_fn2(_args):
        return

    sensor.subscribe(test_fn1, send_period=0.01)
    sensor.subscribe(test_fn2, send_period=0.01)
    assert test_bus.recv(timeout=0.01) is not None
    sensor.unsubscribe_all()
    assert test_bus.recv(timeout=0.02) is None


def test_decode_on_nonsubclassed_device_raises_exc(
    device: Device, output_datapacket: DataPacket
):
    """
    Calling decode on a non-subclassed Device should raise an exception
    """
    with pytest.raises(NotImplementedError):
        device.decode(output_datapacket)


def test_sensor_rx_handler_called(
    qtbot: QtBot,
    sensor: Sensor,
    sensor_datapacket: DataPacket,
    test_bus: can.ThreadSafeBus,
    event_bool: threading.Event,
):
    """
    When a sensor receives a CAN msg addressed to it, it should fire its can_rx_handler
    """
    sensor.subscribe(lambda _arg: event_bool.set(), send_period=0.1)

    with qtbot.waitSignal(
        sensor.sig_value_received, raising=True, timeout=100
    ) as _blocker:
        test_bus.send(sensor_datapacket.to_can_message())

    assert event_bool.is_set(), f"sensor {id} handler was not called"


def test_output_rx_handler_called(
    qtbot: QtBot,
    output: Output,
    output_datapacket: DataPacket,
    test_bus: can.ThreadSafeBus,
    event_bool: threading.Event,
):
    """
    When an output device receives a CAN msg addressed to it, it should fire its can_rx_handler
    """
    output.add_recvr(lambda _arg: event_bool.set())

    with qtbot.waitSignal(
        output.sig_value_received, raising=True, timeout=1000
    ) as _blocker:
        test_bus.send(output_datapacket.to_can_message())

    assert event_bool.is_set(), f"output {id} handler was not called"
