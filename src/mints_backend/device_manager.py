from enum import Enum, StrEnum, unique
from logging import getLogger
from typing import Dict, List

import can
from can.broadcastmanager import CyclicSendTaskABC
from pydantic import BaseModel, ConfigDict, Field, PositiveInt
from PySide6.QtCore import QObject, Signal

from config import boards as BOARDS, config as CFG
from mints_backend.datapacket import (
    CAN_DATA_LEN,
    NODE_ID_MASK,
    RESPONSE_MSG_ID,
    CANCmd,
    CANData,
    DataPacket,
)

log = getLogger(__name__)

# SensorKind = Literal["temperature", "pressure", "load_cell"]

UPDATE_PERIOD = 1


@unique
class SensorKind(StrEnum):
    Temperature = "temperature"
    Pressure = "pressure"
    LoadCell = "load_cell"


@unique
class OutputState(Enum):
    High = True
    Low = False
    Unknown = None


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


class DeviceManager(QObject):
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
            if board_cfg.adc:
                for ch in board_cfg.adc.channels:
                    if ch.name in self.device_registry:
                        raise ValueError(
                            f"Duplicate device name found in board config: {ch.name}"
                        )
                    id = (board_cfg.node_id << 4) + ch.sub_id
                    sensor = Sensor(id, ch.name, SensorKind(ch.kind), self.bus)
                    sensor.subscribe()
                    sensor.sig_conversion_ready.connect(lambda val: log.info("%s", val))

                    self.notifier.add_listener(sensor.handle_can_rx)
                    self.device_registry[ch.name] = sensor

            if board_cfg.outputs:
                for entry in board_cfg.outputs:
                    if entry.name in self.device_registry:
                        raise ValueError(
                            f"Duplicate device name found in board config: {entry.name}"
                        )
                    id = (board_cfg.node_id << 4) + entry.sub_id
                    output = Output(id, entry.name, self.bus)
                    self.notifier.add_listener(output.handle_can_rx)
                    self.device_registry[entry.name] = output


class Device(QObject):
    def __init__(self, id: int, name: str, bus: can.BusABC):
        super().__init__()
        self.id = id
        self.name = name
        self.bus = bus


class Sensor(Device):
    sig_conversion_ready = Signal(int)

    def __init__(self, id, name: str, kind: SensorKind, bus: can.BusABC):
        super().__init__(id, name, bus)
        self.kind = kind
        self._pending: set[int] = set()
        self.subscription: CyclicSendTaskABC | None = None

    def handle_can_rx(self, msg: can.Message):
        try:
            datapacket = DataPacket.from_can_message(msg)
        except ValueError:
            log.error("Sensor %s failed to parse datapacket from CAN msg", self.name)
            return
        if msg.arbitration_id & NODE_ID_MASK != self.id:
            return
        if msg.arbitration_id & ~NODE_ID_MASK != RESPONSE_MSG_ID:
            return
        if datapacket.data.correlation_id not in self._pending:
            return
        val = self.decode(datapacket.data.bytes)
        self.sig_conversion_ready.emit(val)

    def subscribe(self):
        data = CANData(
            correlation_id=None, cmd=CANCmd.ReadReg, bytes=bytearray([0, 0, 0, 0, 0, 0])
        )
        datapacket = DataPacket(self.id, is_err=False, data=data)
        self.subscription = self.bus.send_periodic(
            datapacket.to_can_message(), UPDATE_PERIOD
        )
        self._pending.add(data.correlation_id)

    def unsubscribe(self):
        if self.subscription is None:
            return
        self.subscription.stop()

    def decode(self, bytearray):
        sum = 0
        for byte in bytearray:
            sum += byte
        return sum


class Output(Device):
    def __init__(self, id: int, name: str, bus: can.BusABC):
        super().__init__(id, name, bus)
        self.state: OutputState = OutputState.Unknown

    def handle_can_rx(self, msg: can.Message):
        pass

    def set(self, state: OutputState):
        pass

    def get_state(self):
        pass
