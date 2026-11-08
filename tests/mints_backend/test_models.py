import pytest
from pydantic import ValidationError

from config import boards as BOARD
from mints_backend.models import AdcChannelCfgModel, BoardCfgListModel, OutputCfgModel


@pytest.fixture()
def invalid_board_id():
    yield {"board": [{"board_id": 0xFFF}]}


@pytest.fixture()
def invalid_adc_chan_sub_id():
    yield {"sub_id": 0xFFF, "name": "PT1", "kind": "pressure"}


@pytest.fixture()
def invalid_output_sub_id():
    yield {"sub_id": 0xFFF, "name": "PT1"}


@pytest.fixture()
def duplicate_ids_cfg():
    yield {
        "board": [
            {
                "board_id": 0x1,
                "outputs": [
                    {"sub_id": 0x1, "name": "O1"},
                    {"sub_id": 0x1, "name": "02"},
                ],
            }
        ]
    }


@pytest.fixture()
def duplicate_names_cfg():
    yield {
        "board": [
            {
                "board_id": 0x1,
                "adc": {
                    "channels": [
                        {"sub_id": 0x1, "name": "TT1"},
                        {"sub_id": 0x2, "name": "TT1"},
                    ]
                },
            }
        ]
    }


def test_board_cfg_init_successfully():
    """
    The main BoardCfgListModel should initialize successfully under normal conditions
    """
    _validated_model = BoardCfgListModel.model_validate(BOARD)


def test_duplicate_id_raises_exc(duplicate_ids_cfg):
    """
    A duplicate device id should raise an exception
    """
    with pytest.raises(ValidationError):
        BoardCfgListModel.model_validate(duplicate_ids_cfg)


def test_duplicate_name_raises_exc(duplicate_names_cfg):
    """
    A duplicate device name should raise an exception
    """
    with pytest.raises(ValidationError):
        BoardCfgListModel.model_validate(duplicate_names_cfg)


def test_invalid_board_id_raises_exc(invalid_board_id):
    """
    The model should raise an exception if an invalid board_id is in the config
    """
    with pytest.raises(ValidationError):
        BoardCfgListModel.model_validate(invalid_board_id)


def test_invalid_adc_chan_sub_id_raises_exc(invalid_adc_chan_sub_id):
    """
    The model should raise an exception if an invalid sub_id is in the config
    """
    with pytest.raises(ValidationError):
        AdcChannelCfgModel.model_validate(invalid_adc_chan_sub_id)


def test_invalid_output_sub_id_raises_exc(invalid_output_sub_id):
    """
    The model should raise an exception if an invalid sub_id is in the config
    """
    with pytest.raises(ValidationError):
        OutputCfgModel.model_validate(invalid_output_sub_id)
