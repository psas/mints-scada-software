import can
import pytest

from config import config as CFG
from mints_backend.device_manager import DeviceManager
from mints_backend.models import BoardCfgListModel


@pytest.fixture()
def dev_bus():
    bus: can.BusABC = can.ThreadSafeBus(
        interface="virtual",
        channel="vcan0",
        bitrate=CFG["can"]["bitrate"],
    )

    yield bus

    bus.stop_all_periodic_tasks()
    bus.shutdown()


@pytest.fixture()
def notifier(dev_bus: can.ThreadSafeBus):
    notifier = can.Notifier(dev_bus, listeners=[])
    yield notifier
    notifier.stop()


@pytest.fixture()
def test_bus(request):
    marker = request.node.get_closest_marker("loopback")
    loopback = False if marker is None else marker.args[0]
    bus: can.BusABC = can.ThreadSafeBus(
        interface="virtual",
        channel="vcan0",
        bitrate=CFG["can"]["bitrate"],
        receive_own_messages=loopback,
    )

    yield bus

    bus.stop_all_periodic_tasks()
    bus.shutdown()


@pytest.fixture()
def board_configs():
    yield {
        "board": [
            {"board_id": 0x0, "outputs": [{"sub_id": 0x1, "name": "test"}]},
            {
                "board_id": 0x1,
                "adc": {
                    "channels": [{"sub_id": 0x0, "name": "p0", "kind": "pressure"}]
                },
            },
        ]
    }


@pytest.fixture()
def board_configs_model(board_configs):
    yield BoardCfgListModel.model_validate(board_configs)


@pytest.fixture()
def device_manager(board_configs: dict):
    device_manager = DeviceManager(
        channel="vcan0", virtual_bus=True, board_cfg_dict=board_configs
    )
    yield device_manager
    device_manager.teardown()


@pytest.fixture()
def registry(device_manager):
    yield device_manager.device_registry
