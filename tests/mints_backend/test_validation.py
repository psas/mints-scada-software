import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from mints_backend.models import AdcChannelCfgModel, BoardCfgListModel, OutputCfgModel

test_cfg_path = Path(__file__).parent.parent / "config"

class TestValidation:
    def test_board_id_cfg(self):
        invalid_board_id = test_cfg_path / "invalid_board_id.toml"
        with invalid_board_id.open(mode = "rb") as file:
            data = tomllib.load(file)
        with pytest.raises(ValidationError):
            BoardCfgListModel.model_validate(data)

    def test_adc_sub_id_cfg(self):
        invalid_adc_sub_id = test_cfg_path / "invalid_adc_sub_id.toml"
        with invalid_adc_sub_id.open(mode = "rb") as file:
            data = tomllib.load(file)["board"][0]["adc"]["channels"][0]
        with pytest.raises(ValidationError):
            AdcChannelCfgModel.model_validate(data)

    def test_outputs_sub_id_cfg(self):
        invalid_output_sub_id = test_cfg_path / "invalid_output_sub_id.toml"
        with invalid_output_sub_id.open(mode = "rb") as file:
            data = tomllib.load(file)["board"][1]["outputs"][0]
        with pytest.raises(ValidationError):
            OutputCfgModel.model_validate(data)
