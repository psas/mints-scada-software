import can
import pytest

from mints_backend.datapacket import CAN_DATA_LEN, CANData, DataPacket


@pytest.fixture()
def can_message():
    yield can.Message(
        check=True, arbitration_id=0x123, is_extended_id=False, data=[0] * 8
    )


@pytest.fixture()
def datapacket(can_message: can.Message):
    yield DataPacket.from_can_message(can_message)


@pytest.fixture()
def can_msg_from_datapacket(datapacket: DataPacket):
    yield datapacket.to_can_message()


@pytest.fixture()
def can_data():
    yield CANData(None, bytearray(CAN_DATA_LEN))


@pytest.fixture()
def can_data_to_bytes(can_data: CANData):
    yield can_data.to_bytes()


def test_from_to_can_message(
    can_message: can.Message, can_msg_from_datapacket: can.Message
):
    """
    Datapacket creation from CAN message and conversion from
    datapacket to CAN message should result in equivalent CAN messages
    """
    assert can_msg_from_datapacket.timestamp == can_message.timestamp
    assert can_msg_from_datapacket.arbitration_id == can_message.arbitration_id
    assert can_msg_from_datapacket.is_extended_id == can_message.is_extended_id
    assert can_msg_from_datapacket.is_remote_frame == can_message.is_remote_frame
    assert can_msg_from_datapacket.is_error_frame == can_message.is_error_frame
    assert can_msg_from_datapacket.channel == can_message.channel
    assert can_msg_from_datapacket.dlc == can_message.dlc
    assert can_msg_from_datapacket.data == can_message.data
    assert can_msg_from_datapacket.is_fd == can_message.is_fd
    assert can_msg_from_datapacket.is_rx == can_message.is_rx
    assert can_msg_from_datapacket.bitrate_switch == can_message.bitrate_switch
    assert (
        can_msg_from_datapacket.error_state_indicator
        == can_message.error_state_indicator
    )


def test_candata_checks_data_len():
    """
    CANData __init__ should validate the length of passed in data,
    raising an exception on invalid length and succeeding on the correct length
    """
    with pytest.raises(ValueError):
        CANData(None, bytearray(CAN_DATA_LEN + 1))

    with pytest.raises(ValueError):
        CANData(None, bytearray(CAN_DATA_LEN - 1))

    CANData(None, bytearray(CAN_DATA_LEN))


def test_candata_to_bytes(can_data: CANData, can_data_to_bytes: bytearray):
    """
    Conversion method to go from CANData to a bytearray should yield equivalent bytes
    """
    assert can_data_to_bytes[1:] == can_data.bytes
