from logging import getLogger
from typing import Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt
from PySide6.QtCore import QObject

from config import boards as BOARDS
from mints_backend.can_bus import CanBus

log = getLogger(__name__)


class AdcChannelCfgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: NonNegativeInt
    name: str
    kind: Literal["temperature", "pressure", "load_cell"]


class AdcCfgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channels: List[AdcChannelCfgModel]


class ValveCfgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: NonNegativeInt
    name: str


class BoardCfgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: NonNegativeInt
    adc: AdcCfgModel | None = None
    valves: List[ValveCfgModel] = Field(default_factory=list)


class BoardCfgListModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    board: List[BoardCfgModel]


class DeviceManager(QObject):
    def __init__(self, bus: CanBus):
        super().__init__()
        self.bus: CanBus = bus
        self.board_registry: Dict[int, Board] = {}

        validated_config = BoardCfgListModel.model_validate(BOARDS)

        for board_cfg in validated_config.board:
            board = Board(board_cfg, bus)
            self.board_registry[board_cfg.node_id] = board


class Board(QObject):
    def __init__(self, board_cfg: BoardCfgModel, bus: CanBus):
        super().__init__()
        self.bus = bus
        self.node_id: int = board_cfg.node_id
        valves: List[Valve] = [Valve(valve) for valve in board_cfg.valves]
        if len(valves) > 0:
            self.valves: List[Valve] = valves
        adc_cfg = board_cfg.adc
        if adc_cfg is not None:
            self.adc: Adc = Adc(adc_cfg)


class AdcChannel:
    def __init__(self, adc_chan_cfg: AdcChannelCfgModel):
        super().__init__()
        self.channel = adc_chan_cfg.channel
        self.name = adc_chan_cfg.name
        self.kind = adc_chan_cfg.kind

    def get_val(self):
        return 1000


class Adc:
    def __init__(self, adc_cfg: AdcCfgModel):
        super().__init__()
        self.channels = {}
        for ch in adc_cfg.channels:
            self.channels["ch" + str(ch.channel)] = AdcChannel(ch)


class Valve:
    def __init__(self, valve_cfg: ValveCfgModel):
        super().__init__()
        self.id = valve_cfg.id
        self.name = valve_cfg.name

    def set_on(self):
        pass

    def set_off(self):
        pass

    def get_state(self):
        pass

    def toggle(self):
        pass
