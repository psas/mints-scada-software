from collections.abc import Callable
from logging import getLogger
from typing import override

import can
from can.broadcastmanager import CyclicSendTaskABC
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
from mints_backend.models import (
    AdcChannelCfgModel,
    BoardCfgListModel,
    OutputCfgModel,
    OutputState,
    SensorKind,
)

log = getLogger(__name__)

UPDATE_PERIOD = 1.0


class DeviceManager:
    def __init__(
        self, channel: str | None, virtual_bus=False, board_cfg_dict: dict | None = None
    ):
        self.device_registry: dict[int, Sensor | Output] = {}

        validated_config = BoardCfgListModel.model_validate(
            BOARDS if board_cfg_dict is None else board_cfg_dict
        )

        self.bus: can.BusABC = can.ThreadSafeBus(
            interface=CFG["can"]["interface"] if not virtual_bus else "virtual",
            channel=CFG["can"]["channel"] if channel is None else channel,
            bitrate=CFG["can"]["bitrate"],
        )

        self.notifier = can.Notifier(self.bus, [])

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

    def teardown(self):
        self.notifier.stop()

        for dev in self.device_registry.values():
            match dev:
                case Sensor():
                    dev.unsubscribe()
                case Output():
                    dev.remove_slot_fn()
                case _:
                    raise ValueError(
                        f"Failed to teardown Device Manager: {type(dev)} is not a device"
                    )

        self.bus.stop_all_periodic_tasks()
        self.bus.shutdown()


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

    def subscribe(self, slot_fn: Callable, send_period: float = UPDATE_PERIOD):
        data = CANData(CANCmd.ReadReg, bytearray([0] * CAN_DATA_LEN))
        id = self.id + REQUEST_MSG_ID
        datapacket = DataPacket(id=id, is_err=False, data=data)
        self.subscription = self.bus.send_periodic(
            datapacket.to_can_message(), send_period
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
