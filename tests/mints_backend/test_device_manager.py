import threading
import tomllib
from pathlib import Path

import can
import pytest
from pydantic import ValidationError
from pytestqt.exceptions import TimeoutError as QTimeoutError
from pytestqt.qtbot import QtBot

from config import boards as DEFAULT_BOARDS_CFG
from config import config as CFG
from mints_backend.datapacket import (
    BASE_ID_MSK,
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
)

test_cfgs_path = Path(__file__).parent.parent / "config"


class TestDeviceManager:
    def test_device_manager_init(self):
        """
        Device manager should initialize successfully under normal conditions
        """
        _device_manager = DeviceManager(channel="vcan0", virtual_bus=True)

    def test_bad_channel_raises_os_err(self):
        """
        Passing a bad CAN channel to the device manager should throw an error
        """
        with pytest.raises(OSError):
            _device_manager = DeviceManager(
                channel="why_would_you_ever_name_something_this"
            )

    def test_bad_board_cfg_raises_exception(self):
        """
        Using one of the intentionally error producing board configs should throw an exception
        """
        bad_cfg_path = test_cfgs_path / "typo_board_cfg.toml"
        with bad_cfg_path.open(mode="rb") as file:
            config = tomllib.load(file)

        with pytest.raises(ValidationError):
            _device_manager = DeviceManager(
                "vcan0", virtual_bus=True, board_cfg_file=config
            )

    def test_all_devices_in_registry_have_unique_ids(self):
        """
        Each device in the device manager's registry should have a unique ID
        """
        device_manager = DeviceManager(channel="vcan0", virtual_bus=True)
        registry: dict[int, Sensor | Output] = device_manager.device_registry
        device_ids: set[int] = set()

        for id in registry:
            assert id not in device_ids
            device_ids.add(id)

    def test_duplicate_id_in_register_raises_exception(self):
        """
        If a duplicate ID is detected in the device manager's registry it should raise an exception
        """
        device_manager = DeviceManager(channel="vcan0", virtual_bus=True)
        registry: dict[int, Sensor | Output] = device_manager.device_registry

        if len(registry) == 1:
            pytest.skip("Length of device registry is only 1 - test doesn't apply")

        config = BoardCfgListModel.model_validate(DEFAULT_BOARDS_CFG)
        first_board = config.board[0]
        first_device = (
            first_board.adc.channels[0]
            if first_board.adc is not None
            else first_board.outputs[0]
        )

        with pytest.raises(ValueError):
            device_manager._register_device(first_device, first_board.board_id)

    def test_each_device_rx_handler_registered_as_listener(self):
        """
        Each device in the registry should have its rx_handler registered in the CAN bus notifier list
        """
        device_manager = DeviceManager(channel="vcan0", virtual_bus=True)
        for dev in device_manager.device_registry.values():
            assert dev.handle_can_rx in device_manager.notifier.listeners


class TestDevices:
    test_channel = "vcan0"

    def get_test_bus(self) -> can.BusABC:
        return can.ThreadSafeBus(
            interface="virtual",
            channel=self.test_channel,
            bitrate=CFG["can"]["bitrate"],
        )

    def test_sensors_subscribe_unscubscribe(self):
        """
        Each Sensor Device should send a CAN message when it's subscribed to,
        and shouldn't send messages once it's unsubscribed from
        """
        device_manager = DeviceManager(channel=self.test_channel, virtual_bus=True)
        test_bus: can.BusABC = self.get_test_bus()
        for id, dev in device_manager.device_registry.items():
            match dev:
                case Sensor():
                    # drain any stale messages from previous iterations
                    while test_bus.recv(timeout=0):
                        pass

                    dev.subscribe(lambda _arg: None)
                    try:
                        msg_should_recv: can.Message | None = test_bus.recv(timeout=0.1)
                        assert msg_should_recv is not None, (
                            "No message received after subscribing"
                        )
                        msg_addr = msg_should_recv.arbitration_id & ~BASE_ID_MSK
                        assert msg_addr == id
                    finally:
                        dev.unsubscribe()

                    msg_shouldnt_recv: can.Message | None = test_bus.recv(timeout=0.15)
                    assert msg_shouldnt_recv is None

                case Output():
                    pass

        test_bus.shutdown()

    def test_device_rx_handler_called(self, qtbot: QtBot):
        """
        Every Device should have its CAN rx handler function called when it receives
        a CAN msg addressed to it, and it shouldn't be called if the msg wasn't addressed to it
        """
        device_manager = DeviceManager(channel=self.test_channel, virtual_bus=True)
        test_bus: can.BusABC = self.get_test_bus()
        handler_called = threading.Event()

        for id, dev in device_manager.device_registry.items():
            # drain any stale messages from previous iterations
            while test_bus.recv(timeout=0):
                pass

            assert handler_called.is_set() == False, (
                "handler_called event not cleared between iterations"
            )

            match dev:
                case Sensor():
                    dev.subscribe(lambda _arg: handler_called.set())
                case Output():
                    dev.add_slot_fn(lambda _arg: handler_called.set())
                    dev.get_state()

            try:
                msg: can.Message | None = test_bus.recv(timeout=0.1)
                assert msg is not None, "No message received after subscribing"

                msg_addr = msg.arbitration_id & ~BASE_ID_MSK
                assert msg_addr == id

                resp_id = id + RESPONSE_MSG_ID
                resp_data = CANData(None, bytearray(CAN_DATA_LEN))
                datapacket = DataPacket(id=resp_id, is_err=False, data=resp_data)

                with qtbot.waitSignal(
                    dev.sig_value_received, raising=True, timeout=50
                ) as _blocker:
                    test_bus.send(datapacket.to_can_message())

                assert handler_called.is_set(), f"{id} handler was not called"

                if isinstance(dev, Sensor):
                    dev.unsubscribe()

                with pytest.raises(QTimeoutError):
                    blocker = qtbot.waitSignal(
                        dev.sig_value_received, raising=True, timeout=50
                    )
                    datapacket.id += 1
                    test_bus.send(datapacket.to_can_message())
                    blocker.wait()

            finally:
                handler_called.clear()
                if isinstance(dev, Output):
                    dev.remove_slot_fn()

    def test_decode_on_nonsubclassed_device_raises_exc(self):
        """
        Calling decode on a non-subclassed Device should raise an exception
        """
        test_dev = Device(id=0x123, name="test", bus=self.get_test_bus())
        datapacket = DataPacket(
            id=0x123, is_err=False, data=CANData(None, bytearray(CAN_DATA_LEN))
        )
        with pytest.raises(NotImplementedError):
            test_dev.decode(datapacket)
