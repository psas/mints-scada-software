# backend/device_registry.py

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import Any, Callable

from nexus import Bus, BusRider

import settings
from settings import REQUIRED_DEVICE_FIELDS, normalize_device_desc

log = logging.getLogger(__name__)


def resolve_device_class(device_type: str):
    for prefix in ("electricaldevices", "nexus"):
        try:
            module = importlib.import_module(prefix)
            cls = getattr(module, device_type)
            if not issubclass(cls, BusRider):
                raise ValueError(f"Device type {device_type} must extend BusRider")
            return cls
        except (ImportError, AttributeError):
            continue

    raise ImportError(f"Cannot find a device of type '{device_type}' to add")


def build_device(meta: dict[str, Any]):
    device_class = resolve_device_class(meta["deviceType"])

    device = device_class(
        meta["address"],
        meta["id"],
        **meta["config"],
    )

    device.device_id = meta["id"]
    device.display_name = meta["name"]
    device.address = meta["address"]
    device.meta = meta
    device.live_registered = False
    return device


def maybe_register_device_with_bus(
    bus: Bus,
    device: Any,
    meta: dict[str, Any],
    used_addresses: set[int],
) -> bool:
    if not meta["hasElectricalIO"]:
        log.debug("Skipping bus registration for mechanical-only device %s", meta["id"])
        return False

    if meta["address"] in (None, 0x000, 0):
        log.warning(
            "Skipping live bus registration for %s because address is placeholder %s",
            meta["id"],
            f"{meta['address']:#05x}" if isinstance(meta["address"], int) else meta["address"],
        )
        return False

    if meta["address"] in used_addresses:
        log.warning(
            "Skipping live bus registration for %s because address %s is already in use",
            meta["id"],
            f"{meta['address']:#05x}",
        )
        return False

    bus.addRider(device)
    used_addresses.add(meta["address"])
    log.info("Registered %s on CAN bus at %s", meta["id"], f"{meta['address']:#05x}")
    return True


@dataclass
class DeviceEntry:
    meta: dict[str, Any]
    runtime: Any


class DeviceRegistry:
    """Backend-owned runtime device inventory."""

    def __init__(self) -> None:
        self._entries_by_id: dict[str, DeviceEntry] = {}
        self._load_errors: list[str] = []
        self._packet_listener: Callable[[dict[str, Any], Any, Any], None] | None = None

    def set_packet_listener(
        self,
        listener: Callable[[dict[str, Any], Any, Any], None] | None,
    ) -> None:
        self._packet_listener = listener

    def load_from_settings(self) -> None:
        self._entries_by_id.clear()
        self._load_errors.clear()

        for device_desc in settings.devices:
            try:
                meta = normalize_device_desc(device_desc)
                runtime = build_device(meta)
                self._install_runtime_packet_hook(meta, runtime)
                self._entries_by_id[meta["id"]] = DeviceEntry(meta=meta, runtime=runtime)
            except Exception as exc:
                device_id = device_desc.get("id", "<unknown>")
                message = f"Failed to load device {device_id}: {exc}"
                self._load_errors.append(message)
                log.exception(message)

    def register_active_devices_with_bus(self, bus: Bus) -> dict[str, Any]:
        used_addresses: set[int] = set()
        registered_ids: list[str] = []
        skipped_ids: list[str] = []

        for entry in self._entries_by_id.values():
            meta = entry.meta
            runtime = entry.runtime

            if not meta["isActive"]:
                runtime.live_registered = False
                skipped_ids.append(meta["id"])
                continue

            try:
                runtime.live_registered = maybe_register_device_with_bus(
                    bus=bus,
                    device=runtime,
                    meta=meta,
                    used_addresses=used_addresses,
                )
            except Exception:
                runtime.live_registered = False
                raise

            if runtime.live_registered:
                registered_ids.append(meta["id"])
            else:
                skipped_ids.append(meta["id"])

        return {
            "registered_ids": registered_ids,
            "skipped_ids": skipped_ids,
            "registered_count": len(registered_ids),
            "skipped_count": len(skipped_ids),
        }

    def clear_live_registration_flags(self) -> None:
        for entry in self._entries_by_id.values():
            entry.runtime.live_registered = False

    def get_gui_device_presentations(self) -> list[dict[str, Any]]:
        """Return presentation-safe inventory summaries for GUI consumption."""
        return [
            {
                "id": entry.meta["id"],
                "name": entry.meta["name"],
                "deviceType": entry.meta["deviceType"],
                "deviceGroup": entry.meta["deviceGroup"],
                "deviceSystems": list(entry.meta["deviceSystems"]),
                "address": entry.meta["address"],
                "hasElectricalIO": entry.meta["hasElectricalIO"],
                "isControllable": entry.meta["isControllable"],
                "widgetType": entry.meta["widgetType"],
                "isActive": entry.meta["isActive"],
                "live_registered": bool(getattr(entry.runtime, "live_registered", False)),
            }
            for entry in self._entries_by_id.values()
        ]

    def get_device_summaries(self) -> list[dict[str, Any]]:
        """Backward-compatible alias for older callers."""
        return self.get_gui_device_presentations()

    def get_load_errors(self) -> list[str]:
        return list(self._load_errors)

    def get_runtime(self, device_id: str) -> Any:
        return self._entries_by_id[device_id].runtime

    def get_meta(self, device_id: str) -> dict[str, Any]:
        return dict(self._entries_by_id[device_id].meta)

    def __contains__(self, device_id: str) -> bool:
        return device_id in self._entries_by_id

    def __len__(self) -> int:
        return len(self._entries_by_id)

    def _install_runtime_packet_hook(self, meta: dict[str, Any], runtime: Any) -> None:
        if getattr(runtime, "_backend_packet_hook_installed", False):
            return

        original_on_packet = runtime._onPacket

        def wrapped_on_packet(packet, _original=original_on_packet, _meta=meta, _runtime=runtime):
            _original(packet)

            listener = self._packet_listener
            if listener is None:
                return

            if packet is None:
                return

            if getattr(packet, "id", None) != getattr(_runtime, "_id", None):
                return

            listener(dict(_meta), _runtime, packet)

        runtime._onPacket = wrapped_on_packet
        runtime._backend_packet_hook_installed = True