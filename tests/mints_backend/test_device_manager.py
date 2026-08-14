import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from mints_backend.device_manager import DeviceManager

test_cfgs_path = Path(__file__).parent.parent / "config"

class TestDeviceManager:
    def test_device_manager_init(self):
        """
        Test that the device manager is able to initialize
        """
        _device_manager = DeviceManager(channel="vcan0", virtual_bus=True)

    def test_bad_channel_raises_os_err(self):
        """
        Test that passing a bad channel name to the device manager produces an exception
        """
        with pytest.raises(OSError):
            _device_manager = DeviceManager(
                channel="why_would_you_ever_name_something_this"
            )

    def test_bad_board_cfg_raises_exception(self):

        bad_cfg_path = test_cfgs_path / "typo_board_cfg.toml"
        with bad_cfg_path.open(mode="rb") as file:
            config = tomllib.load(file)

        with pytest.raises(ValidationError):
            _device_manager = DeviceManager("vcan0", virtual_bus=True, board_cfg=config)




