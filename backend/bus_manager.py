from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from nexus import Bus

import settings

from .device_registry import DeviceRegistry

log = logging.getLogger(__name__)


@dataclass
class BusInitResult:
    sender: str
    bitrate: int
    registered_ids: list[str]
    skipped_ids: list[str]
    registered_count: int
    skipped_count: int


class BusManager:
    """Backend-owned bus lifecycle wrapper.

    Current scope:
    - create Bus
    - start/stop Bus lifecycle
    - register active devices through DeviceRegistry

    Later commits can expand this into:
    - exception routing
    - reconnect policy
    - packet fanout into reducer/history
    """

    def __init__(
        self,
        *,
        sender: str | None = None,
        bitrate: int | None = None,
        packetprinting: bool = False,
        packetlogging: bool = False,
    ) -> None:
        self.sender = sender if sender is not None else settings.sender
        self.bitrate = bitrate if bitrate is not None else settings.bitrate
        self.packetprinting = packetprinting
        self.packetlogging = packetlogging

        self._bus: Bus | None = None
        self._entered = False

    @property
    def bus(self) -> Bus | None:
        return self._bus

    @property
    def is_running(self) -> bool:
        return self._bus is not None and self._entered

    def initialize_live_hardware(self, registry: DeviceRegistry) -> BusInitResult:
        if self.is_running:
            raise RuntimeError("BusManager is already running")

        bus = Bus(
            self.sender,
            self.bitrate,
            packetprinting=self.packetprinting,
            packetlogging=self.packetlogging,
        )

        try:
            bus.__enter__()
            self._bus = bus
            self._entered = True

            registration = registry.register_active_devices_with_bus(bus)

            return BusInitResult(
                sender=self.sender,
                bitrate=self.bitrate,
                registered_ids=registration["registered_ids"],
                skipped_ids=registration["skipped_ids"],
                registered_count=registration["registered_count"],
                skipped_count=registration["skipped_count"],
            )

        except Exception:
            log.exception("Failed to initialize live hardware")
            self._safe_shutdown_current_bus()
            raise

    def shutdown_live_hardware(self) -> None:
        if not self.is_running:
            return
        self._safe_shutdown_current_bus()

    def _safe_shutdown_current_bus(self) -> None:
        bus = self._bus
        self._bus = None
        self._entered = False

        if bus is None:
            return

        try:
            bus.__exit__(None, None, None)
        except Exception:
            log.exception("Error while shutting down BusManager")