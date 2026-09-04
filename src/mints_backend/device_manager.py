from __future__ import annotations

import sys
from logging import getLogger

import can
from pydantic import ValidationError

from config import boards as BOARDS
from config import config as CFG
from mints_backend.devices import Output, Sensor
from mints_backend.models import (
    AdcChannelCfgModel,
    BoardCfgListModel,
    OutputCfgModel,
    SensorKind,
)

log = getLogger(__name__)
can.util.set_logging_level("WARN")


def try_setup_device_manager(bus: str) -> DeviceManager:
    try:
        return DeviceManager(bus)
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
                    dev.unsubscribe_all()
                case Output():
                    dev.remove_all_slot_fns()
                case _:
                    raise ValueError(
                        f"Failed to teardown Device Manager: {type(dev)} is not a device"
                    )

        self.bus.stop_all_periodic_tasks()
        self.bus.shutdown()
