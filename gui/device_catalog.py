# gui/device_catalog.py

from __future__ import annotations

from typing import Any

from settings import normalize_device_desc


def build_gui_meta_from_settings_device_desc(device_desc: dict[str, Any]) -> dict[str, Any]:
    meta = normalize_device_desc(device_desc)
    meta["live_registered"] = False
    return meta


class BackendDeviceProxy:
    """Lightweight GUI-side proxy for a backend-owned device runtime."""

    def __init__(self, meta: dict[str, Any]) -> None:
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
        self.meta.update(summary)
        self.live_registered = bool(summary.get("live_registered", self.live_registered))

    def apply_runtime_state(self, runtime_state: dict[str, Any]) -> None:
        self.online = bool(runtime_state.get("online", self.online))
        self.value = runtime_state.get("runtime_value")
        self.aux = runtime_state.get("runtime_aux")
        self.time = runtime_state.get("runtime_time")

    def to_presentation_dict(self) -> dict[str, Any]:
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
        return f"BackendDeviceProxy(device_id={self.device_id!r}, name={self.display_name!r})"


class BackendDeviceCatalog:
    """GUI-owned presentation catalog.

    The catalog owns GUI-side proxies only.
    It never owns backend runtime authority or bus access.
    """

    def __init__(self) -> None:
        self._devices_by_id: dict[str, BackendDeviceProxy] = {}

    def sync_inventory(self, devices: list[dict[str, Any]]) -> list[BackendDeviceProxy]:
        """Apply backend inventory summaries.

        Returns a list of proxies that were newly created so callers can attach
        them to existing GUI views/layouts.
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
        """Build GUI-only playback proxies from static settings device configs."""
        presentation_summaries = [
            build_gui_meta_from_settings_device_desc(device_desc)
            for device_desc in device_descs
        ]
        return self.sync_inventory(presentation_summaries)

    def apply_state_snapshot(self, snapshot: dict[str, Any]) -> None:
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
        return self._devices_by_id.get(device_id)

    def get_all_proxies(self) -> list[BackendDeviceProxy]:
        return list(self._devices_by_id.values())

    def to_presentation_snapshot(self) -> dict[str, Any]:
        return {
            "devices": [proxy.to_presentation_dict() for proxy in self._devices_by_id.values()],
        }

    def __contains__(self, device_id: str) -> bool:
        return device_id in self._devices_by_id

    def __len__(self) -> int:
        return len(self._devices_by_id)