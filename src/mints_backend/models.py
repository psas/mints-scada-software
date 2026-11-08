from typing import Self

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, model_validator

from mints_backend.devices import SensorKind


class AdcChannelCfgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sub_id: NonNegativeInt
    name: str
    kind: SensorKind

    @model_validator(mode="after")
    def validate_adc_sub_id(self) -> Self:
        if self.sub_id > 0x7:
            raise ValueError("ADC sub_id out of range. Must be between 0 and 7.")
        return self


class AdcCfgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channels: list[AdcChannelCfgModel]


class OutputCfgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sub_id: NonNegativeInt
    name: str

    @model_validator(mode="after")
    def validate_output_sub_id(self) -> Self:
        if self.sub_id > 0x7:
            raise ValueError("Output sub_id out of range. Must be between 0 and 7")
        return self


class BoardCfgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    board_id: NonNegativeInt
    adc: AdcCfgModel | None = None
    outputs: list[OutputCfgModel] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_board_id(self) -> Self:
        if self.board_id > 0xF:
            raise ValueError("board_id out of range. Must be between 0 and 15.")
        return self


class BoardCfgListModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    board: list[BoardCfgModel]

    @model_validator(mode="after")
    def validate_unique_names_ids(self) -> Self:
        seen_names = set()
        seen_ids = set()

        def check_for_duplicates(
            board: BoardCfgModel, dev: AdcChannelCfgModel | OutputCfgModel
        ) -> None:
            if dev.name in seen_names:
                raise ValueError(f"Duplicate device name found in config: {dev.name}")
            seen_names.add(dev.name)
            id = (board.board_id << 4) | dev.sub_id
            if id in seen_ids:
                raise ValueError(
                    f"Duplicate device id found in config - id: {hex(id)}, board_id: {hex(board.board_id)}, sub_id: {hex(dev.sub_id)}"
                )
            seen_ids.add(id)

        for board in self.board:
            for dev in board.outputs:
                check_for_duplicates(board, dev)

            if board.adc is None:
                continue

            for dev in board.adc.channels:
                check_for_duplicates(board, dev)

        return self
