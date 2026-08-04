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
        self.device_registry: Dict[str, AdcChannel | Valve] = {}

        validated_config = BoardCfgListModel.model_validate(BOARDS)

        for board_cfg in validated_config.board:
            board = Board(board_cfg)
            self.board_registry[board_cfg.node_id] = board

        for node_id, board in self.board_registry.items():
            for adc_channel in board.adc.channels:
                self.device_registry[adc_channel.name] = adc_channel


class Device:
    def __init__(self, node_id: int, name: str):
        self.node_id = node_id
        self.name = name


class Sensor(Device):
    def __init__(self, node_id: int, adc_channel: int, name: str):
        super().__init__(node_id, name)
        self.adc_channel = adc_channel

    def read(self):
        pass


class PressureSensor(Sensor):
    def __init__(self, node_id: int, adc_channel: int, name: str):
        super().__init__(node_id, adc_channel, name)


class TemperatureSensor(Sensor):
    def __init__(self, node_id: int, adc_channel: int, name: str):
        super().__init__(node_id, adc_channel, name)


class LoadCellSensor(Sensor):
    def __init__(self, node_id: int, adc_channel: int, name: str):
        super().__init__(node_id, adc_channel, name)


class Valve(Device):
    def __init__(self, node_id: int, valve_cfg: ValveCfgModel):
        super().__init__(node_id, valve_cfg.name)
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


class Board(QObject):
    def __init__(self, board_cfg: BoardCfgModel):
        super().__init__()
        self.node_id: int = board_cfg.node_id
        valves: List[Valve] = [
            Valve(board_cfg.node_id, valve) for valve in board_cfg.valves
        ]
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
