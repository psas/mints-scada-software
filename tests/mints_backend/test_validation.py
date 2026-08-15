import pytest
from pathlib import Path
from pydantic import ValidationError
from mints_backend.models import AdcChannelCfgModel, BoardCfgListModel, OutputCfgModel

test_cfg_path = Path(__file__).parent.parent / "config.invalid_id_cfg"

class TestValidation:
    def test_board_id_cfg(self):
        with pytest.raises(ValidationError):
            BoardCfgListModel.model_validate(test_cfg_path)

    def test_adc_sub_id_cfg(self):
        with pytest.raises(ValidationError):
            AdcChannelCfgModel.model_validate(test_cfg_path)

    def test_outputs_sub_id_cfg(self):
        with pytest.raises(ValidationError):
            OutputCfgModel.model_validate(test_cfg_path)
