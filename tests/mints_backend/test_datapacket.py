import can
import pytest

from mints_backend.datapacket import CAN_DATA_LEN, CANData, DataPacket


class TestDataPacket:
    def test_from_to_can_message(self):
        """
        Test datapacket creation from CAN message and conversion from
        datapacket to CAN message results in equivalent CAN messages
        """
        mock_msg = can.Message(
            check=True, arbitration_id=0x123, is_extended_id=False, data=[0] * 8
        )

        datapacket = DataPacket.from_can_message(mock_msg)
        msg: can.Message = datapacket.to_can_message()

        assert msg.timestamp == mock_msg.timestamp
        assert msg.arbitration_id == mock_msg.arbitration_id
        assert msg.is_extended_id == mock_msg.is_extended_id
        assert msg.is_remote_frame == mock_msg.is_remote_frame
        assert msg.is_error_frame == mock_msg.is_error_frame
        assert msg.channel == mock_msg.channel
        assert msg.dlc == mock_msg.dlc
        assert msg.data == mock_msg.data
        assert msg.is_fd == mock_msg.is_fd
        assert msg.is_rx == mock_msg.is_rx
        assert msg.bitrate_switch == mock_msg.bitrate_switch
        assert msg.error_state_indicator == mock_msg.error_state_indicator

    def test_candata_checks_data_len(self):
        """
        Test that CANData __init__ validates the length of passed in data,
        raising an exception on invalid length and succeeding on the correct length
        """
        with pytest.raises(ValueError):
            data_too_long = bytearray([0] * (CAN_DATA_LEN + 1))
            _bad_can_data = CANData(None, data_too_long)

        with pytest.raises(ValueError):
            data_too_short = bytearray([0] * (CAN_DATA_LEN - 1))
            _bad_can_data = CANData(None, data_too_short)

        good_data = bytearray([0] * CAN_DATA_LEN)
        _good_can_data = CANData(None, good_data)

    def test_candata_to_bytes(self):
        mock_bytes = bytearray([0] * CAN_DATA_LEN)
        can_data = CANData(None, mock_bytes)
        converted_data = can_data.to_bytes()
        assert converted_data[1:] == mock_bytes
