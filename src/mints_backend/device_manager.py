from enum import Enum, StrEnum, unique
from logging import getLogger
from typing import Callable, Dict, List

import can
from can.broadcastmanager import CyclicSendTaskABC
from pydantic import BaseModel, ConfigDict, Field, PositiveInt
from PySide6.QtCore import QObject, Signal

from config import boards as BOARDS
from config import config as CFG
from mints_backend.datapacket import (
    CAN_DATA_LEN,
    NODE_ID_MASK,
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
    sub_id: PositiveInt
    name: str
    kind: SensorKind


class AdcCfgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channels: List[AdcChannelCfgModel]


class OutputCfgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sub_id: PositiveInt
    name: str


class BoardCfgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: PositiveInt
    adc: AdcCfgModel | None = None
    outputs: List[OutputCfgModel] = Field(default_factory=list)


class BoardCfgListModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    board: List[BoardCfgModel]


class DeviceManager:
    def __init__(self, channel: str):
        super().__init__()
        self.device_registry: Dict[str, Sensor | Output] = {}
        try:
            self.bus = can.ThreadSafeBus(
                interface=CFG["can"]["interface"],
                channel=CFG["can"]["channel"] if channel is None else channel,
                bitrate=CFG["can"]["bitrate"],
            )
        except OSError as e:
            raise OSError from e

        self.notifier = can.Notifier(self.bus, [])

        validated_config = BoardCfgListModel.model_validate(BOARDS)

        for board_cfg in validated_config.board:
            for cfg in board_cfg.adc.channels if board_cfg.adc else []:
                self._register_device(cfg, board_cfg.node_id)
            for cfg in board_cfg.outputs:
                self._register_device(cfg, board_cfg.node_id)

    def _register_device(self, cfg: OutputCfgModel | AdcChannelCfgModel, node_id: int):
        if cfg.name in self.device_registry:
            raise ValueError(f"Duplicate device name found in board config: {cfg.name}")
        id = (node_id << 4) + cfg.sub_id
        match cfg:
            case OutputCfgModel():
                dev = Output(id, cfg.name, self.bus)
            case AdcChannelCfgModel():
                dev = Sensor(id, cfg.name, SensorKind(cfg.kind), self.bus)
        self.notifier.add_listener(dev.handle_can_rx)
        self.device_registry[cfg.name] = dev


class Device(QObject):
    sig_value_received = Signal(int)

    def __init__(self, id: int, name: str, bus: can.BusABC):
        super().__init__()
        self.id = id
        self.name = name
        self.bus = bus
        self._pending: set[int] = set()

    def handle_can_rx(self, msg: can.Message):
        try:
            datapacket = DataPacket.from_can_message(msg)
        except ValueError:
            log.error("Sensor '%s' failed to parse datapacket from CAN msg", self.name)
            return

        recipient_node_id = msg.arbitration_id & NODE_ID_MASK
        base_id = msg.arbitration_id & BASE_ID_MASK

        if (
            recipient_node_id != self.id
            or base_id != RESPONSE_MSG_ID
            or datapacket.data.correlation_id not in self._pending
        ):
            return

        val = self.decode(datapacket.data.bytes)
        self.sig_value_received.emit(val)

    def send_cmd(self, cmd: CANCmd, cmd_params: bytearray):
        padded_params = bytearray(
            cmd_params + (bytearray([0] * (CAN_DATA_LEN - len(cmd_params))))
        )
        data = CANData(None, cmd, padded_params)
        datapacket = DataPacket(id=self.id, is_err=False, data=data)
        self.bus.send(datapacket.to_can_message())
        self._pending.add(data.correlation_id)

    def decode(self, bytearray):
        sum = 0
        for byte in bytearray:
            sum += byte
        return sum


class Sensor(Device):
    def __init__(self, id: int, name: str, kind: SensorKind, bus: can.BusABC):
        super().__init__(id, name, bus)
        self.kind = kind
        self.subscription: CyclicSendTaskABC | None = None

    def subscribe(self, slot_fn: Callable):
        data = CANData(None, CANCmd.ReadReg, bytearray([0] * CAN_DATA_LEN))
        datapacket = DataPacket(id=self.id, is_err=False, data=data)
        self.subscription = self.bus.send_periodic(
            datapacket.to_can_message(), UPDATE_PERIOD
        )
        self._pending.add(data.correlation_id)
        self.sig_value_received.connect(slot_fn)

    def unsubscribe(self):
        if self.subscription is None:
            return
        self.subscription.stop()
        self.sig_value_received.disconnect()


class Output(Device):
    def __init__(self, id: int, name: str, bus: can.BusABC):
        super().__init__(id, name, bus)
        self.state: OutputState | None = None

    def set_state(self, state: OutputState):
        self.send_cmd(CANCmd.SetOutput, bytearray([state.value]))

    def get_state(self):
        self.send_cmd(CANCmd.GetOutput, bytearray([0]))

    def add_slot_fn(self, slot_fn: Callable):
        self.sig_value_received.connect(slot_fn)

    def remove_slot_fn(self):
        self.sig_value_received.disconnect()
