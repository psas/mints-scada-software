from collections.abc import Callable
from enum import Enum, StrEnum, unique
from logging import getLogger
from typing import Self, override

import can
from can.broadcastmanager import CyclicSendTaskABC
from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, model_validator
from PySide6.QtCore import QObject, Signal

from config import boards as BOARDS
from config import config as CFG
from mints_backend.datapacket import (
    ADDR_MSK,
    BASE_ID_MSK,
    CAN_DATA_LEN,
    OUTPUT_SET_POS,
    REQUEST_MSG_ID,
    RESPONSE_MSG_ID,
    CANCmd,
    CANData,
    DataPacket,
)

log = getLogger(__name__)

UPDATE_PERIOD = 1


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


class DeviceManager:
    def __init__(self, channel: str | None, virtual_bus=False, board_cfg_file=None):
        super().__init__()
        self.device_registry: dict[int, Sensor | Output] = {}
        self.bus = can.ThreadSafeBus(
            interface=CFG["can"]["interface"] if not virtual_bus else "virtual",
            channel=CFG["can"]["channel"] if channel is None else channel,
            bitrate=CFG["can"]["bitrate"],
        )

        self.notifier = can.Notifier(self.bus, [])

        validated_config = BoardCfgListModel.model_validate(
            BOARDS if board_cfg_file is None else board_cfg_file
        )

        for board_cfg in validated_config.board:
            for cfg in board_cfg.adc.channels if board_cfg.adc else []:
                self._register_device(cfg, board_cfg.board_id)
            for cfg in board_cfg.outputs:
                self._register_device(cfg, board_cfg.board_id)

    def _register_device(self, cfg: OutputCfgModel | AdcChannelCfgModel, board_id: int):
        id = (board_id << 4) + cfg.sub_id
        match cfg:
            case OutputCfgModel():
                dev = Output(id, cfg.name, self.bus)
            case AdcChannelCfgModel():
                dev = Sensor(id, cfg.name, SensorKind(cfg.kind), self.bus)
        self.notifier.add_listener(dev.handle_can_rx)
        if id in self.device_registry:
            raise ValueError(f"Duplicate device ID found in registry: {id}")
        self.device_registry[id] = dev


class Device(QObject):
    sig_value_received = Signal(int)

    def __init__(self, id: int, name: str, bus: can.BusABC):
        super().__init__()
        self.id = id
        self.name = name
        self.bus = bus

    def handle_can_rx(self, msg: can.Message):
        base_id = msg.arbitration_id & BASE_ID_MSK
        addr = msg.arbitration_id & ADDR_MSK
        if addr != self.id or base_id != RESPONSE_MSG_ID:
            return

        try:
            datapacket = DataPacket.from_can_message(msg)
        except ValueError:
            log.error("Sensor '%s' failed to parse datapacket from CAN msg", self.name)
            return

        val = self.decode(datapacket)
        self.sig_value_received.emit(val)

    def send_cmd(self, cmd: CANCmd, cmd_params: bytearray):
        data = CANData(cmd, cmd_params)
        arbitration_id = REQUEST_MSG_ID | self.id
        datapacket = DataPacket(id=arbitration_id, is_err=False, data=data)
        self.bus.send(datapacket.to_can_message())

    def decode(self, _datapacket: DataPacket) -> int:
        raise NotImplementedError


class Sensor(Device):
    def __init__(self, id: int, name: str, kind: SensorKind, bus: can.BusABC):
        super().__init__(id, name, bus)
        self.kind = kind
        self.subscription: CyclicSendTaskABC | None = None

    def subscribe(self, slot_fn: Callable):
        data = CANData(CANCmd.ReadReg, bytearray([0] * CAN_DATA_LEN))
        id = self.id + REQUEST_MSG_ID
        datapacket = DataPacket(id=id, is_err=False, data=data)
        self.subscription = self.bus.send_periodic(
            datapacket.to_can_message(), UPDATE_PERIOD
        )
        self.sig_value_received.connect(slot_fn)

    def unsubscribe(self):
        if self.subscription is None:
            return
        self.subscription.stop()
        self.sig_value_received.disconnect()

    @override
    def decode(self, datapacket: DataPacket) -> int:
        sum = 0
        for byte in datapacket.data.bytes:
            sum += byte
        return sum


class Output(Device):
    def __init__(self, id: int, name: str, bus: can.BusABC):
        super().__init__(id, name, bus)
        self.state: OutputState | None = None

    def set_state(self, state: OutputState) -> None:
        bytes = bytearray(CAN_DATA_LEN)
        bytes[OUTPUT_SET_POS] = state.value

        self.send_cmd(CANCmd.SetOutput, bytes)

    def get_state(self) -> None:
        self.send_cmd(CANCmd.GetOutput, bytearray(CAN_DATA_LEN))

    def add_slot_fn(self, slot_fn: Callable) -> None:
        self.sig_value_received.connect(slot_fn)

    def remove_slot_fn(self) -> None:
        self.sig_value_received.disconnect()

    def decode(self, datapacket: DataPacket) -> int:
        return datapacket.data.bytes[OUTPUT_SET_POS]
