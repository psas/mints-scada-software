import can
import pytest

from mints_backend.device_manager import DeviceManager
from mints_backend.models import BoardCfgListModel


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
