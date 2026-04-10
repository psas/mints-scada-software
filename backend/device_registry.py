# backend/device_registry.py

"""Backend-owned device inventory and live bus registration helpers.

This module loads normalized device descriptors from ``settings.py`` into
runtime device instances, tracks them in a backend registry, and optionally
registers active electrical devices onto the live CAN bus.
"""

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
    """Resolve a runtime device class by name.

    The lookup checks the ``electricaldevices`` package first and then
    ``nexus``. The resolved class must extend ``BusRider`` so the backend can
    treat it as a bus-connected runtime device.

    Args:
        device_type: Class name declared by the normalized device descriptor.

    Returns:
        The resolved device class.

    Raises:
        ValueError: The resolved attribute exists but does not extend
            ``BusRider``.
        ImportError: No matching device class can be found in the supported
            packages.
    """
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
    """Instantiate a backend runtime device from normalized metadata.

    The created runtime is annotated with backend-facing convenience attributes
    such as ``device_id``, ``display_name``, the original normalized metadata,
    and the live-registration flag used during bus initialization.

    Args:
        meta: Normalized device descriptor produced by
            ``settings.normalize_device_desc``.

    Returns:
        The instantiated runtime device.

    Raises:
        ValueError: The declared device class does not extend ``BusRider``.
        ImportError: The declared device class cannot be resolved.
        Exception: Propagated from the device constructor when instantiation
            fails.
    """
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
    """Register a runtime device with the live bus when its metadata allows it.

    Registration is skipped for mechanical-only devices, placeholder addresses,
    and addresses already claimed earlier in the current registration pass.

    Args:
        bus: Live bus that owns runtime riders.
        device: Runtime device instance to register.
        meta: Normalized device descriptor for ``device``.
        used_addresses: Addresses already claimed during the current
            registration pass.

    Returns:
        True when ``device`` is added to the bus. False when registration is
        skipped because the descriptor is not eligible for live electrical
        registration.
    """
    if not meta["hasElectricalIO"]:
        log.debug("Skipping bus registration for mechanical-only device %s", meta["id"])
        return False

    if meta["address"] in (None, 0x000, 0):
        log.warning(
            "Skipping live bus registration for %s because address is placeholder %s",
            meta["id"],
            (
                f"{meta['address']:#05x}"
                if isinstance(meta["address"], int)
                else meta["address"]
            ),
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
    """Pair normalized device metadata with its runtime instance."""

    meta: dict[str, Any]
    runtime: Any


class DeviceRegistry:
    """Store backend runtime devices loaded from the static settings catalog."""

    def __init__(self) -> None:
        """Initialize an empty runtime inventory and optional packet listener."""
        self._entries_by_id: dict[str, DeviceEntry] = {}
        self._load_errors: list[str] = []
        self._packet_listener: Callable[[dict[str, Any], Any, Any], None] | None = None

    def set_packet_listener(
        self,
        listener: Callable[[dict[str, Any], Any, Any], None] | None,
    ) -> None:
        """Set the callback notified after runtime devices handle matching packets.

        Args:
            listener: Callback that receives a metadata copy, the runtime
                device, and the packet that was processed. Pass None to clear
                the current listener.

        Returns:
            None.
        """
        self._packet_listener = listener

    def load_from_settings(self) -> None:
        """Rebuild the registry from ``settings.devices``.

        Each descriptor is normalized, instantiated into a runtime device, and
        wrapped with the backend packet hook before being stored by canonical
        device ID. Individual load failures are recorded in ``_load_errors`` and
        do not stop the rest of the catalog from loading.

        Returns:
            None.
        """
        self._entries_by_id.clear()
        self._load_errors.clear()

        for device_desc in settings.devices:
            try:
                meta = normalize_device_desc(device_desc)
                runtime = build_device(meta)
                self._install_runtime_packet_hook(meta, runtime)
                self._entries_by_id[meta["id"]] = DeviceEntry(
                    meta=meta, runtime=runtime
                )
            except Exception as exc:
                device_id = device_desc.get("id", "<unknown>")
                message = f"Failed to load device {device_id}: {exc}"
                self._load_errors.append(message)
                log.exception(message)

    def register_active_devices_with_bus(self, bus: Bus) -> dict[str, Any]:
        """Register active runtime devices with the live bus.

        Only entries whose normalized metadata declares ``isActive`` are
        considered. Each candidate is passed through
        ``maybe_register_device_with_bus``, and the runtime's
        ``live_registered`` flag is updated to match the outcome.

        Args:
            bus: Live bus to populate with active runtime riders.

        Returns:
            A summary dictionary containing registered and skipped device IDs
            plus their counts.

        Raises:
            Exception: Propagated when bus registration fails unexpectedly for a
                candidate device.
        """
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
        """Mark every runtime device as not live-registered.

        Returns:
            None.
        """
        for entry in self._entries_by_id.values():
            entry.runtime.live_registered = False

    def get_gui_device_presentations(self) -> list[dict[str, Any]]:
        """Build presentation-safe inventory summaries for GUI consumers.

        Returns:
            A list of dictionaries containing normalized device metadata plus
            the runtime ``live_registered`` status.
        """
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
                "live_registered": bool(
                    getattr(entry.runtime, "live_registered", False)
                ),
            }
            for entry in self._entries_by_id.values()
        ]

    def get_device_summaries(self) -> list[dict[str, Any]]:
        """Return the backward-compatible GUI presentation list.

        Returns:
            The same presentation-safe inventory summaries returned by
            ``get_gui_device_presentations``.
        """
        return self.get_gui_device_presentations()

    def get_load_errors(self) -> list[str]:
        """Return the accumulated device-load error messages.

        Returns:
            A shallow copy of the current load-error list.
        """
        return list(self._load_errors)

    def get_runtime(self, device_id: str) -> Any:
        """Return the runtime device instance for a canonical device ID.

        Args:
            device_id: Canonical device identifier.

        Returns:
            The stored runtime device instance.

        Raises:
            KeyError: The device ID is not present in the registry.
        """
        return self._entries_by_id[device_id].runtime

    def get_meta(self, device_id: str) -> dict[str, Any]:
        """Return normalized metadata for a canonical device ID.

        Args:
            device_id: Canonical device identifier.

        Returns:
            A shallow copy of the stored normalized metadata.

        Raises:
            KeyError: The device ID is not present in the registry.
        """
        return dict(self._entries_by_id[device_id].meta)

    def __contains__(self, device_id: str) -> bool:
        """Return whether the registry contains ``device_id``.

        Args:
            device_id: Canonical device identifier.

        Returns:
            True when the registry has an entry for ``device_id``.
        """
        return device_id in self._entries_by_id

    def __len__(self) -> int:
        """Return the number of loaded device entries.

        Returns:
            The number of registry entries keyed by device ID.
        """
        return len(self._entries_by_id)

    def _install_runtime_packet_hook(self, meta: dict[str, Any], runtime: Any) -> None:
        """Wrap a runtime device packet handler with backend listener notification.

        The wrapper preserves the runtime's original ``_onPacket`` behavior,
        then forwards matching packets to the registry-wide packet listener when
        one is configured. Hooks are installed at most once per runtime object.

        Args:
            meta: Normalized metadata associated with ``runtime``.
            runtime: Runtime device instance whose packet handler should be
                wrapped.

        Returns:
            None.
        """
        if getattr(runtime, "_backend_packet_hook_installed", False):
            return

        original_on_packet = runtime._onPacket

        def wrapped_on_packet(
            packet, _original=original_on_packet, _meta=meta, _runtime=runtime
        ):
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
