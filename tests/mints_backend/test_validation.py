
import pytest
from pydantic import ValidationError

from config import boards as BOARD
from mints_backend.models import AdcChannelCfgModel, BoardCfgListModel, OutputCfgModel


class TestValidation:
    def test_board_cfg_init_successfully(self):
        """
        The main BoardCfgListModel should initialize successfully under normal conditions
        """
        _validated_model = BoardCfgListModel.model_validate(BOARD)

    def test_invalid_board_id_raises_exc(self):
        """
        The model should raise an exception if an invalid board_id is in the config
        """
        data = {"board": [{"board_id": 0xFFF}]}
        with pytest.raises(ValidationError):
            BoardCfgListModel.model_validate(data)

    def test_invalid_adc_sub_id_raises_exc(self):
        """
        The model should raise an exception if an invalid sub_id is in the config
        """
        data = {"sub_id": 0xFFF, "name": "PT1", "kind": "pressure"}
        with pytest.raises(ValidationError):
            AdcChannelCfgModel.model_validate(data)

    def test_invalid_output_sub_id_raises_exc(self):
        """
        The model should raise an exception if an invalid sub_id is in the config
        """
        data = {"sub_id": 0xFFF, "name": "PT1"}
        with pytest.raises(ValidationError):
            OutputCfgModel.model_validate(data)
