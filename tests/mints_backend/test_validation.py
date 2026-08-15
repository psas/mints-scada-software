from pathlib import Path
from pydantic import ValidationError
import pytest
import tomllib

from mints_backend.models import BoardCfgListModel, OutputCfgModel, AdcChannelCfgModel

bad_board_id = Path(__file__).parent.parent / "config" / "invalid_board_id.toml"

with bad_board_id.open(mode="rb") as file:
    CFG = tomllib.load(file)

class TestModelValidation:

    def test_asc_channel_cfg_validation(self):
        with pytest.raises(ValidationError):
            OutputCfgModel.model_validate(CFG)

    def test_output_cfg_validation(self):
        with pytest.raises(ValidationError):
            AdcChannelCfgModel.model_validate(CFG)

    def test_board_cfg_validation(self):
        with pytest.raises(ValidationError):
            BoardCfgListModel.model_validate(CFG)

