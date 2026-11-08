import can
import pytest
from pyqtgraph.parametertree import Parameter
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from mints_backend.datapacket import (
    CAN_DATA_LEN,
    OUTPUT_SET_POS,
    RESPONSE_MSG_ID,
    CANData,
    DataPacket,
)
from mints_backend.device_manager import DeviceManager
from mints_backend.devices import OutputState
from mints_gui.ui.widgets.device_tree import (
    DeviceParameterTree,
    OutputButton,
    OutputParameter,
)


@pytest.fixture()
def device_param_tree(device_manager: DeviceManager, qtbot: QtBot):
    # Pass in qtbot to make sure a QApp is loaded before creating widgets
    device_param_tree = DeviceParameterTree(device_manager)
    yield device_param_tree


@pytest.fixture()
def board_param(device_param_tree: DeviceParameterTree):
    yield device_param_tree.root.children()[0]


@pytest.fixture()
def output_cfg(board_configs: dict):
    board_cfg = board_configs["board"][0]
    yield board_cfg["outputs"][0]


@pytest.fixture()
def output_param(board_param: Parameter):
    yield board_param.children()[0]


@pytest.fixture()
def output_button(qtbot: QtBot, output_param: OutputParameter):
    output_button = next(iter(output_param.items)).widget
    qtbot.addWidget(output_button)
    yield output_button


@pytest.fixture()
def output_button_datapacket(output_cfg: dict, board_configs: dict):
    bytes = bytearray(CAN_DATA_LEN)
    bytes[OUTPUT_SET_POS] = OutputState.Low.value  # Set closed
    data = CANData(None, bytes)
    board_id = board_configs["board"][0]["board_id"]
    arbitration_id = RESPONSE_MSG_ID + (board_id << 4) + output_cfg["sub_id"]
    yield DataPacket(id=arbitration_id, is_err=False, data=data)


def test_param_tree_init_success(
    device_manager: DeviceManager, device_param_tree: DeviceParameterTree
):
    """
    The DeviceParameterTree should initialize successfully under normal conditions
    """
    assert isinstance(device_param_tree.device_manager, DeviceManager)
    assert isinstance(device_param_tree.root, Parameter)


def test_devices_created_with_proper_name(
    board_configs: dict,
    board_param: Parameter,
    output_param: OutputParameter,
    output_cfg: dict,
):
    """
    The tree should give devices a name that matches the config
    """
    assert board_param.name() == "Board " + hex(board_configs["board"][0]["board_id"])
    assert output_param.name() == output_cfg["name"]


def test_output_triggers_can_msg_on_click(
    device_param_tree: DeviceParameterTree,
    output_cfg: dict,
    output_param: OutputParameter,
    output_button: OutputButton,
    test_bus: can.ThreadSafeBus,
    qtbot: QtBot,
):
    """
    When clicked, the output button should send a CAN msg with its sub_id
    telling the firmware to toggle the output state
    """
    with qtbot.waitSignal(output_param.sigValueChanged, timeout=250) as _blocker:
        qtbot.mouseClick(output_button, Qt.MouseButton.LeftButton)
    assert test_bus.recv(timeout=0.1) is not None


def test_can_rx_sets_btn_state(
    board_configs: dict,
    device_param_tree: DeviceParameterTree,
    output_cfg: dict,
    output_param: OutputParameter,
    output_button: OutputButton,
    output_button_datapacket: DataPacket,
    test_bus: can.ThreadSafeBus,
    qtbot: QtBot,
):
    """
    When the button receives a CAN msg addressed to it it should update its state
    """
    with qtbot.waitSignal(output_param.sigUpdateFromBackend) as _blocker:
        test_bus.send(output_button_datapacket.to_can_message())
    assert output_button.text() == "Closed"
