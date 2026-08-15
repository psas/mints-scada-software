from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator
from enum import Enum, StrEnum, unique
from typing_extensions import Self

@unique
class SensorKind(StrEnum):
    Temperature = "temperature"
    Pressure = "pressure"
    LoadCell = "load_cell"


@unique
class OutputState(Enum):
    High = 1
    Low = 0


class AdcChannelCfgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sub_id: PositiveInt
    name: str
    kind: SensorKind

    @model_validator(mode='after')
    def validate_adc_sub_id(self) -> Self:
        if self.sub_id < 0x200 or self.sub_id > 0x800:
            raise ValueError("ADC sub_id out of range. Must be between 0x200 and 0x800.")
        return self


class AdcCfgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channels: list[AdcChannelCfgModel]


class OutputCfgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sub_id: PositiveInt
    name: str

    @model_validator(mode='after')
    def validate_output_sub_id(self) -> Self:
        if self.sub_id < 0x200 or self.sub_id > 0x800:
            raise ValueError("Output sub_id out of range. Must be between 0x200 and 0x800.")
        return self


class BoardCfgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    board_id: PositiveInt
    adc: AdcCfgModel | None = None
    outputs: list[OutputCfgModel] = Field(default_factory=list)
    
    @model_validator(mode='after')
    def validate_board_id(self) -> Self:
        if self.board_id < 0x10 or self.board_id > 0x80:
            raise ValueError("board_id out of range. Must be between 0x10 and 0x80.")
        return self


class BoardCfgListModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    board: list[BoardCfgModel]

