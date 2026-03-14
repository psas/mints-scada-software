from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import Any

from nexus import Bus, BusRider

import settings

log = logging.getLogger(__name__)

REQUIRED_DEVICE_FIELDS = (
    "id",
    "name",
    "deviceType",
    "deviceGroup",
    "deviceSystems",
    "address",
    "hasElectricalIO",
    "isControllable",
    "widgetType",
    "isActive",
)


def normalize_device_desc(device_desc: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in REQUIRED_DEVICE_FIELDS if key not in device_desc]
    if missing:
        raise KeyError(
            f"Device config is missing required fields: {missing}\nConfig: {device_desc}"
        )

    meta = {
        "id": device_desc["id"],
        "name": device_desc["name"],
        "deviceType": device_desc["deviceType"],
        "deviceGroup": device_desc["deviceGroup"],
        "deviceSystems": (
            list(device_desc["deviceSystems"]) if device_desc["deviceSystems"] else []
        ),
        "address": device_desc["address"],
        "hasElectricalIO": bool(device_desc["hasElectricalIO"]),
        "isControllable": bool(device_desc["isControllable"]),
        "widgetType": device_desc["widgetType"],
        "isActive": bool(device_desc["isActive"]),
        "config": dict(device_desc.get("config", {})),
    }

    if not isinstance(meta["deviceSystems"], list):
        raise TypeError(f"deviceSystems must be a list for device {meta['id']}")

    return meta


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

    # Attach schema metadata to the runtime object.
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

    def load_from_settings(self) -> None:
        self._entries_by_id.clear()
        self._load_errors.clear()

        for device_desc in settings.devices:
            try:
                meta = normalize_device_desc(device_desc)
                runtime = build_device(meta)
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

    def get_device_summaries(self) -> list[dict[str, Any]]:
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