from __future__ import annotations

import sys
from collections import UserDict
from logging import getLogger

import can
from pydantic import ValidationError

from config import boards as BOARDS
from config import config as CFG
from mints_backend.devices import Device, Output, Sensor
from mints_backend.models import (
    AdcChannelCfgModel,
    BoardCfgListModel,
    OutputCfgModel,
    SensorKind,
)

log = getLogger(__name__)
can.util.set_logging_level("WARN")


def try_setup_device_manager(chan: str | None = None) -> DeviceManager:
    try:
        return DeviceManager(channel=chan)
    except ValidationError as e:
        err_details = e.errors()
        for err in err_details:
            log.error(
                "Validation error in board config file. Field: %s. Found: '%s' - %s",
                err["loc"],
                err["input"],
                err["msg"],
            )
        sys.exit(1)
    except OSError as e:
        log.error("Unable to connect to CAN bus - %s", e.strerror)
        sys.exit(e.errno)


class DeviceManager:
    def __init__(
        self, channel: str | None, virtual_bus=False, board_cfg_dict: dict | None = None
    ):
        self.device_registry = DeviceRegistry()

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
        self.device_registry.register(dev)

    def teardown(self):
        self.notifier.stop()

        for dev in self.device_registry:
            match dev:
                case Sensor():
                    dev.unsubscribe_all()
                case Output():
                    dev.remove_all_recvrs()
                case _:
                    raise ValueError(
                        f"Failed to teardown Device Manager: {type(dev)} is not a device"
                    )

        self.bus.stop_all_periodic_tasks()
        self.bus.shutdown()


class DeviceRegistry(UserDict):
    def __contains__(self, item) -> bool:
        return item in self.data

    def __getitem__(self, key: int) -> Sensor | Output:
        return self.data[key]

    def __setitem__(self, key: int, item: Sensor | Output) -> None:
        self.data[key] = item

    def __delitem__(self, key: int) -> None:
        del self.data[key]

    def __len__(self) -> int:
        return len(self.data)

    def __iter__(self):
        return iter(self.data.values())

    def __repr__(self):
        return f"DeviceRegistry({self.data})"

    def register(self, dev: Device) -> None:
        if dev.id in self.ids:
            raise ValueError("Attempted to register device already in registry")
        self.data[dev.id] = dev

    @property
    def ids(self) -> list[int]:
        return list(self.data.keys())

    @property
    def sensors(self) -> list[Sensor]:
        return [dev for dev in self.data.values() if isinstance(dev, Sensor)]

    @property
    def outputs(self) -> list[Output]:
        return [dev for dev in self.data.values() if isinstance(dev, Output)]

    def get_by_id(self, id: int) -> Sensor | Output:
        return self.data[id]

    def get_by_name(self, name: str) -> Sensor | Output:
        return next(iter(dev for dev in self.data.values() if dev.name == name))
