import threading

import can
import pytest
from pytestqt.qtbot import QtBot

from mints_backend.datapacket import (
    CAN_DATA_LEN,
    RESPONSE_MSG_ID,
    CANData,
    DataPacket,
)
from mints_backend.device_manager import (
    BoardCfgListModel,
    Device,
    DeviceManager,
    Output,
    Sensor,
    SensorKind,
)


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


def test_device_manager_init(device_manager: DeviceManager):
    """
    Device manager should initialize successfully under normal conditions,
    and with proper attributes
    """
    assert isinstance(device_manager.bus, can.ThreadSafeBus)
    assert isinstance(device_manager.notifier, can.Notifier)
    assert len(device_manager.device_registry) > 0


def test_bad_channel_raises_os_err():
    """
    Passing a bad CAN channel to the device manager should throw an error
    """
    with pytest.raises(OSError):
        _device_manager = DeviceManager(
            channel="why_would_you_ever_name_something_this"
        )


def test_duplicate_id_in_register_raises_exception(
    device_manager: DeviceManager, board_configs_model: BoardCfgListModel
):
    """
    If a duplicate ID is detected in the device manager's registry it should raise an exception
    """
    with pytest.raises(ValueError):
        device_manager._register_device(
            next(iter(board_configs_model.board)).outputs[0],
            next(iter(board_configs_model.board)).board_id,
        )


def test_each_device_rx_handler_registered_as_listener(device_manager: DeviceManager):
    """
    Each device in the registry should have its rx_handler registered in the CAN bus notifier list
    """
    for dev in device_manager.device_registry.values():
        assert dev.handle_can_rx in device_manager.notifier.listeners


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
    sensor.subscribe(lambda _args: None, send_period=0.01)
    assert test_bus.recv(timeout=0.01) is not None
    sensor.unsubscribe()
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
    output.add_slot_fn(lambda _arg: event_bool.set())

    with qtbot.waitSignal(
        output.sig_value_received, raising=True, timeout=1000
    ) as _blocker:
        test_bus.send(output_datapacket.to_can_message())

    assert event_bool.is_set(), f"output {id} handler was not called"
