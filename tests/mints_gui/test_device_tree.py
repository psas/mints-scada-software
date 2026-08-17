import can
import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from config import config as CFG
from mints_backend.datapacket import (
    CAN_DATA_LEN,
    OUTPUT_SET_POS,
    RESPONSE_MSG_ID,
    SUB_ID_MSK,
    CANData,
    DataPacket,
)
from mints_backend.device_manager import DeviceManager
from mints_backend.models import OutputState
from mints_gui.ui.device_tree import DeviceParameterTree


@pytest.fixture()
def board_configs():
    yield {"board": [{"board_id": 0x0, "outputs": [{"sub_id": 0x1, "name": "test"}]}]}


@pytest.fixture()
def device_manager(board_configs):
    device_manager = DeviceManager(
        channel="vcan0", virtual_bus=True, board_cfg_dict=board_configs
    )
    yield device_manager
    device_manager.teardown()


@pytest.fixture()
def device_param_tree(device_manager):
    device_param_tree = DeviceParameterTree(device_manager)
    yield device_param_tree
    device_param_tree.teardown()


@pytest.fixture()
def board(device_param_tree):
    yield device_param_tree.root.children()[0]


@pytest.fixture()
def output_cfg(board_configs):
    board_cfg = board_configs["board"][0]
    yield board_cfg["outputs"][0]


@pytest.fixture()
def output(board):
    yield board.children()[0]


@pytest.fixture()
def test_bus():
    bus = can.ThreadSafeBus(
        channel="vcan0", interface="virtual", bitrate=CFG["can"]["bitrate"]
    )
    yield bus
    bus.shutdown()


class TestDeviceTree:
    def test_param_tree_init_success(self, device_manager, device_param_tree):
        """
        The DeviceParameterTree should initialize successfully under normal conditions
        """
        # The test is done by the fixtures
        assert True

    def test_devices_created_with_proper_name(self, board_configs, board, output):
        """
        The tree should give devices a name that matches the config
        """
        board_cfg = board_configs["board"][0]
        output_cfg = board_cfg["outputs"][0]

        assert board.name() == "Board " + hex(board_cfg["board_id"])
        assert output.name() == output_cfg["name"]

    def test_output_triggers_can_msg_on_click(
        self, output, output_cfg, device_param_tree, test_bus, qtbot: QtBot
    ):
        """
        When clicked, the output button should send a CAN msg with its sub_id
        telling the firmware to toggle the output state
        """
        output_button = next(iter(output.items)).widget
        qtbot.addWidget(output_button)

        with qtbot.waitSignal(output.sigValueChanged, timeout=250) as _blocker:
            qtbot.mouseClick(output_button, Qt.MouseButton.LeftButton)

        msg: can.Message | None = test_bus.recv(timeout=0.1)
        assert msg is not None

        sub_id = output_cfg["sub_id"]
        msg_sub_id = msg.arbitration_id & SUB_ID_MSK
        assert msg_sub_id == sub_id

    def test_can_rx_sets_btn_state(
        self, device_param_tree, output, output_cfg, board_configs, test_bus, qtbot
    ):
        """
        When the button receives a CAN msg addressed to it it should update its state
        """
        output_button = next(iter(output.items)).widget
        qtbot.addWidget(output_button)

        bytes = bytearray(CAN_DATA_LEN)
        bytes[OUTPUT_SET_POS] = OutputState.Low.value  # Set closed
        data = CANData(None, bytes)
        board_id = board_configs["board"][0]["board_id"]
        arbitration_id = RESPONSE_MSG_ID + (board_id << 4) + output_cfg["sub_id"]
        dp = DataPacket(id=arbitration_id, is_err=False, data=data)

        with qtbot.waitSignal(output.sigUpdateFromBackend) as _blocker:
            test_bus.send(dp.to_can_message())

        assert output_button.text() == "Closed"
