from __future__ import annotations

from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.gui


class _FakeProxy:
    def __init__(self, device_id: str, meta: dict) -> None:
        self.device_id = device_id
        self.meta = dict(meta)


class _FakeCatalogForInventory:
    def __init__(self):
        self.synced_devices = None

    def sync_inventory(self, devices):
        self.synced_devices = [dict(device) for device in devices]
        return [_FakeProxy(device_id=device["id"], meta=device) for device in devices]

    def to_presentation_snapshot(self):
        return {"source": "inventory", "count": len(self.synced_devices or [])}


class _FakeCatalogForSnapshot:
    def __init__(self):
        self.snapshot = None
        self.synced_devices = []

    def apply_state_snapshot(self, snapshot):
        self.snapshot = dict(snapshot)

    def sync_inventory(self, devices):
        self.synced_devices = [dict(device) for device in devices]
        return [_FakeProxy(device_id=device["id"], meta=device) for device in devices]

    def to_presentation_snapshot(self):
        return {"source": "snapshot", "count": len(self.synced_devices)}


class _WindowRecorder:
    def __init__(self):
        self.added = []

    def addDevice(self, proxy, meta):
        self.added.append((proxy, dict(meta)))



def test_bridge_on_device_inventory_adds_devices_to_window():
    from gui.window_host import GuiBackendBridge

    window = _WindowRecorder()
    fake_self = SimpleNamespace(window=window, device_catalog=_FakeCatalogForInventory())
    payload = {
        "devices": [
            {"id": "ig-xv-01", "name": "Igniter Valve", "isActive": True, "hasElectricalIO": True},
            {"id": "lox-xv-26", "name": "LOX Valve", "isActive": True, "hasElectricalIO": False},
        ]
    }

    GuiBackendBridge.on_device_inventory(fake_self, payload)

    assert [meta["id"] for _, meta in window.added] == ["ig-xv-01", "lox-xv-26"]
    assert getattr(window, "backend_device_inventory")["devices"][0]["id"] == "ig-xv-01"
    assert getattr(window, "backend_device_presentation") == {"source": "inventory", "count": 2}



def test_bridge_on_state_snapshot_should_seed_device_library_when_snapshot_contains_devices():
    from gui.window_host import GuiBackendBridge

    window = _WindowRecorder()
    fake_self = SimpleNamespace(window=window, device_catalog=_FakeCatalogForSnapshot())
    snapshot = {
        "device_registry": {
            "devices": [
                {"id": "ig-xv-01", "name": "Igniter Valve", "isActive": True, "hasElectricalIO": True},
                {"id": "lox-xv-26", "name": "LOX Valve", "isActive": True, "hasElectricalIO": False},
            ],
            "total_devices": 2,
            "load_errors": [],
            "load_error_count": 0,
        },
        "health": {},
    }

    GuiBackendBridge.on_state_snapshot(fake_self, snapshot)

    assert [meta["id"] for _, meta in window.added] == ["ig-xv-01", "lox-xv-26"]
    assert getattr(window, "backend_device_presentation") == {"source": "snapshot", "count": 2}



def test_bridge_on_state_snapshot_does_not_require_live_registered_true_to_show_active_devices():
    from gui.window_host import GuiBackendBridge

    window = _WindowRecorder()
    fake_self = SimpleNamespace(window=window, device_catalog=_FakeCatalogForSnapshot())
    snapshot = {
        "device_registry": {
            "devices": [
                {
                    "id": "ig-xv-01",
                    "name": "Igniter Valve",
                    "isActive": True,
                    "hasElectricalIO": True,
                    "live_registered": False,
                },
                {
                    "id": "lox-xv-26",
                    "name": "LOX Valve",
                    "isActive": True,
                    "hasElectricalIO": False,
                    "live_registered": False,
                },
            ],
            "total_devices": 2,
            "load_errors": [],
            "load_error_count": 0,
        },
        "health": {},
    }

    GuiBackendBridge.on_state_snapshot(fake_self, snapshot)

    added_by_id = {meta["id"]: meta for _, meta in window.added}
    assert set(added_by_id) == {"ig-xv-01", "lox-xv-26"}
    assert added_by_id["ig-xv-01"]["live_registered"] is False
    assert added_by_id["lox-xv-26"]["live_registered"] is False
