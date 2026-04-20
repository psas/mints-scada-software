"""gui/device_catalog.py

GUI-side device presentation catalog backed by backend snapshots.

This module builds presentation metadata from the shared settings device schema
and exposes lightweight proxy objects that mirror backend-owned inventory and
runtime state for existing GUI views.
"""

from __future__ import annotations

from typing import Any

from settings import normalize_device_desc


def build_gui_meta_from_settings_device_desc(
    device_desc: dict[str, Any],
) -> dict[str, Any]:
    """Build GUI presentation metadata from a static settings device descriptor.

    The descriptor is first normalized through the shared settings schema so the
    GUI playback path uses the same canonical metadata shape as the backend
    inventory path. The returned metadata is marked as not live-registered.

    Args:
        device_desc: Static device descriptor from ``settings.devices``.

    Returns:
        A normalized device metadata dictionary with ``live_registered`` forced
        to False.
    """
    meta = normalize_device_desc(device_desc)
    meta["live_registered"] = False
    return meta


class BackendDeviceProxy:
    """Lightweight GUI-side proxy for a backend-owned device runtime.

    The proxy stores presentation metadata plus a small set of runtime-like
    fields that existing GUI widgets and views already expect.
    """

    def __init__(self, meta: dict[str, Any]) -> None:
        """Initialize a presentation proxy from backend or settings metadata.

        Args:
            meta: Canonical device metadata used to seed the GUI-side proxy.
        """
        self.meta = dict(meta)

        self.device_id = self.meta["id"]
        self.display_name = self.meta["name"]
        self.name = self.meta["name"]
        self.address = self.meta["address"]
        self._id = self.meta["address"]

        self.live_registered = bool(self.meta.get("live_registered", False))

        # Runtime-like fields for existing widgets/views.
        self.value = None
        self.aux = None
        self.time = None
        self.online = False

    def apply_inventory_summary(self, summary: dict[str, Any]) -> None:
        """Merge backend inventory metadata into the proxy.

        Args:
            summary: Backend inventory summary for this device.

        Returns:
            None.
        """
        self.meta.update(summary)
        self.live_registered = bool(
            summary.get("live_registered", self.live_registered)
        )

    def apply_runtime_state(self, runtime_state: dict[str, Any]) -> None:
        """Apply backend runtime fields to the proxy.

        Args:
            runtime_state: Runtime state snapshot for this device from the
                backend ``device_runtime.by_id`` mapping.

        Returns:
            None.
        """
        self.online = bool(runtime_state.get("online", self.online))
        self.value = runtime_state.get("runtime_value")
        self.aux = runtime_state.get("runtime_aux")
        self.time = runtime_state.get("runtime_time")

    def to_presentation_dict(self) -> dict[str, Any]:
        """Build a GUI-facing snapshot of this proxy.

        Returns:
            A presentation dictionary containing device identity, live
            registration status, runtime-like fields, and a copy of the
            underlying metadata.
        """
        return {
            "device_id": self.device_id,
            "display_name": self.display_name,
            "address": self.address,
            "live_registered": self.live_registered,
            "online": self.online,
            "value": self.value,
            "aux": self.aux,
            "time": self.time,
            "meta": dict(self.meta),
        }

    def __repr__(self) -> str:
        """Return a compact debug representation for the proxy.

        Returns:
            A representation that includes the device id and display name.
        """
        return f"BackendDeviceProxy(device_id={self.device_id!r}, name={self.display_name!r})"


class BackendDeviceCatalog:
    """GUI-owned presentation catalog of backend device proxies.

    The catalog owns GUI-side proxy objects only. It does not own backend
    runtime authority, hardware access, or bus communication.
    """

    def __init__(self) -> None:
        """Initialize an empty proxy catalog."""
        self._devices_by_id: dict[str, BackendDeviceProxy] = {}

    def sync_inventory(self, devices: list[dict[str, Any]]) -> list[BackendDeviceProxy]:
        """Apply backend inventory summaries to the catalog.

        New device ids create new proxies. Existing device ids update the
        matching proxy metadata in place.

        Args:
            devices: Inventory summary dictionaries, typically from the backend
                device registry snapshot.

        Returns:
            The proxies that were created during this sync so callers can attach
            them to existing GUI views or layouts.
        """
        newly_created: list[BackendDeviceProxy] = []

        for device_summary in devices:
            if not isinstance(device_summary, dict):
                continue

            device_id = device_summary.get("id")
            if not isinstance(device_id, str):
                continue

            proxy = self._devices_by_id.get(device_id)
            if proxy is None:
                proxy = BackendDeviceProxy(device_summary)
                self._devices_by_id[device_id] = proxy
                newly_created.append(proxy)
            else:
                proxy.apply_inventory_summary(device_summary)

        return newly_created

    def seed_from_settings_devices(
        self,
        device_descs: list[dict[str, Any]],
    ) -> list[BackendDeviceProxy]:
        """Seed playback-capable proxies from static settings device descriptors.

        Args:
            device_descs: Static device descriptors, usually sourced from
                ``settings.devices``.

        Returns:
            The proxies created from the normalized settings metadata.
        """
        presentation_summaries = [
            build_gui_meta_from_settings_device_desc(device_desc)
            for device_desc in device_descs
        ]
        return self.sync_inventory(presentation_summaries)

    def apply_state_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Apply a backend-style state snapshot to inventory and runtime proxies.

        The method first syncs any device registry inventory entries, then
        applies per-device runtime fields from ``device_runtime.by_id`` to
        proxies that already exist in the catalog.

        Args:
            snapshot: Backend-style full-state snapshot.

        Returns:
            None.
        """
        device_registry = snapshot.get("device_registry", {})
        registry_devices = device_registry.get("devices", [])
        if isinstance(registry_devices, list):
            self.sync_inventory(registry_devices)

        device_runtime = snapshot.get("device_runtime", {}).get("by_id", {})
        if not isinstance(device_runtime, dict):
            return

        for device_id, runtime_state in device_runtime.items():
            proxy = self._devices_by_id.get(device_id)
            if proxy is None or not isinstance(runtime_state, dict):
                continue
            proxy.apply_runtime_state(runtime_state)

    def get_proxy(self, device_id: str) -> BackendDeviceProxy | None:
        """Return the proxy for a device id when present.

        Args:
            device_id: Canonical device identifier.

        Returns:
            The matching proxy, or None when the catalog does not contain the
            device id.
        """
        return self._devices_by_id.get(device_id)

    def get_all_proxies(self) -> list[BackendDeviceProxy]:
        """Return all proxies currently tracked by the catalog.

        Returns:
            A list of all device proxies in insertion order.
        """
        return list(self._devices_by_id.values())

    def to_presentation_snapshot(self) -> dict[str, Any]:
        """Build a presentation snapshot of the entire catalog.

        Returns:
            A dictionary containing serialized presentation dictionaries for all
            tracked proxies.
        """
        return {
            "devices": [
                proxy.to_presentation_dict() for proxy in self._devices_by_id.values()
            ],
        }

    def __contains__(self, device_id: str) -> bool:
        """Return whether the catalog contains a device id.

        Args:
            device_id: Canonical device identifier.

        Returns:
            True when the catalog has a proxy for ``device_id``.
        """
        return device_id in self._devices_by_id

    def __len__(self) -> int:
        """Return the number of tracked device proxies.

        Returns:
            The number of proxies stored in the catalog.
        """
        return len(self._devices_by_id)
