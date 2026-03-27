from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.backend


@dataclass
class DummyRuntime:
    live_registered: bool = False

    def __post_init__(self) -> None:
        self._backend_packet_hook_installed = False
        self._onPacket = lambda packet: None



def _device(
    device_id: str,
    *,
    is_active: bool,
    has_electrical_io: bool,
    is_controllable: bool = True,
    address: int = 0x10,
    systems: list[str] | None = None,
    widget_type: str = "sensor",
) -> dict:
    return {
        "id": device_id,
        "name": f"Device {device_id}",
        "deviceType": "GenericSensor" if has_electrical_io else "GenericActuator",
        "deviceGroup": "XV" if is_controllable else "PC",
        "deviceSystems": list(systems or ["IG"]),
        "address": address,
        "hasElectricalIO": has_electrical_io,
        "isControllable": is_controllable,
        "widgetType": widget_type,
        "isActive": is_active,
    }



def test_device_registry_loads_presentations_from_settings_before_live_init(monkeypatch):
    import backend.device_registry as device_registry_module

    devices = [
        _device("ig-xv-01", is_active=True, has_electrical_io=True, address=0x21),
        _device(
            "ig-pc-01",
            is_active=False,
            has_electrical_io=False,
            is_controllable=False,
            address=0x00,
            widget_type="mechanical",
        ),
        _device(
            "lox-xv-26",
            is_active=True,
            has_electrical_io=False,
            address=0x66,
            widget_type="mechanical",
            systems=["LOX"],
        ),
    ]

    monkeypatch.setattr(device_registry_module.settings, "devices", devices, raising=False)
    monkeypatch.setattr(device_registry_module, "build_device", lambda meta: DummyRuntime())

    registry = device_registry_module.DeviceRegistry()
    registry.load_from_settings()

    presentations = registry.get_gui_device_presentations()
    ids = {item["id"] for item in presentations}
    active_ids = {item["id"] for item in presentations if item["isActive"]}

    assert registry.get_load_errors() == []
    assert ids == {"ig-xv-01", "ig-pc-01", "lox-xv-26"}
    assert active_ids == {"ig-xv-01", "lox-xv-26"}
    assert all(item["live_registered"] is False for item in presentations)



def test_register_active_devices_with_bus_does_not_hide_inventory_when_registration_skips_or_waits(monkeypatch):
    import backend.device_registry as device_registry_module

    devices = [
        _device("ig-xv-01", is_active=True, has_electrical_io=True, address=0x21),
        _device(
            "ig-pc-01",
            is_active=False,
            has_electrical_io=False,
            is_controllable=False,
            address=0x00,
            widget_type="mechanical",
        ),
        _device(
            "lox-xv-26",
            is_active=True,
            has_electrical_io=False,
            address=0x66,
            widget_type="mechanical",
            systems=["LOX"],
        ),
    ]

    monkeypatch.setattr(device_registry_module.settings, "devices", devices, raising=False)
    monkeypatch.setattr(device_registry_module, "build_device", lambda meta: DummyRuntime())

    def fake_maybe_register_device_with_bus(*, bus, device, meta, used_addresses):
        return meta["id"] == "ig-xv-01"

    monkeypatch.setattr(
        device_registry_module,
        "maybe_register_device_with_bus",
        fake_maybe_register_device_with_bus,
    )

    registry = device_registry_module.DeviceRegistry()
    registry.load_from_settings()
    result = registry.register_active_devices_with_bus(bus=SimpleNamespace())
    presentations = registry.get_gui_device_presentations()

    assert result["registered_ids"] == ["ig-xv-01"]
    assert set(result["skipped_ids"]) == {"ig-pc-01", "lox-xv-26"}

    presentation_by_id = {item["id"]: item for item in presentations}
    assert set(presentation_by_id) == {"ig-xv-01", "ig-pc-01", "lox-xv-26"}
    assert presentation_by_id["ig-xv-01"]["live_registered"] is True
    assert presentation_by_id["lox-xv-26"]["live_registered"] is False
    assert presentation_by_id["lox-xv-26"]["isActive"] is True
    assert presentation_by_id["ig-pc-01"]["isActive"] is False


class _FakeHistoryManager:
    def __init__(self, *args, **kwargs) -> None:
        self.is_running = False


class _FakeHealthPublisher:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def set_raw_mirror_callback(self, callback) -> None:
        self._raw_mirror_callback = callback

    def record_system_event(self, *args, **kwargs) -> None:
        pass


class _FakeBusManager:
    def __init__(self, *args, **kwargs) -> None:
        self.callbacks = {}

    def set_event_callbacks(self, **kwargs) -> None:
        self.callbacks = dict(kwargs)

    def shutdown_live_hardware(self) -> None:
        pass


class _FakeGatewayClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeScriptRunner:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def shutdown(self) -> None:
        pass


class _FakeBackendHealthMonitor:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def sample_once(self) -> None:
        pass


class _FakeIPCServer:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def stop(self) -> None:
        pass

    def serve_forever(self) -> None:
        pass


class _FakeRegistry:
    def __init__(self):
        self.listener = None
        self.load_from_settings_called = False
        self.clear_live_registration_flags_called = False
        self._devices = [
            {
                "id": "ig-xv-01",
                "name": "Igniter Valve",
                "deviceType": "GenericActuator",
                "deviceGroup": "XV",
                "deviceSystems": ["IG"],
                "address": 0x21,
                "hasElectricalIO": True,
                "isControllable": True,
                "widgetType": "sensor",
                "isActive": True,
                "live_registered": False,
            },
            {
                "id": "lox-xv-26",
                "name": "LOX Valve",
                "deviceType": "GenericActuator",
                "deviceGroup": "XV",
                "deviceSystems": ["LOX"],
                "address": 0x66,
                "hasElectricalIO": False,
                "isControllable": True,
                "widgetType": "mechanical",
                "isActive": True,
                "live_registered": False,
            },
        ]

    def set_packet_listener(self, listener) -> None:
        self.listener = listener

    def load_from_settings(self) -> None:
        self.load_from_settings_called = True

    def get_gui_device_presentations(self):
        return list(self._devices)

    def get_load_errors(self):
        return []

    def clear_live_registration_flags(self) -> None:
        self.clear_live_registration_flags_called = True



def test_backend_service_seeds_device_inventory_into_state_store_at_startup(monkeypatch, tmp_path):
    import backend.service as service_module

    fake_registry = _FakeRegistry()

    monkeypatch.setattr(service_module, "HistoryManager", _FakeHistoryManager)
    monkeypatch.setattr(service_module, "HealthPublisher", _FakeHealthPublisher)
    monkeypatch.setattr(service_module, "BusManager", _FakeBusManager)
    monkeypatch.setattr(service_module, "GatewayClient", _FakeGatewayClient)
    monkeypatch.setattr(service_module, "RunController", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(service_module, "Reducer", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(service_module, "StructuredEventBuilder", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(service_module, "CommandRouter", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(service_module, "ScriptRunner", _FakeScriptRunner)
    monkeypatch.setattr(service_module, "BackendHealthMonitor", _FakeBackendHealthMonitor)
    monkeypatch.setattr(service_module, "IPCServer", _FakeIPCServer)
    monkeypatch.setattr(service_module, "DeviceRegistry", lambda: fake_registry)

    service = service_module.BackendService(project_root=tmp_path)
    snapshot = service.state_store.get_snapshot()["device_registry"]

    assert fake_registry.load_from_settings_called is True
    assert snapshot["total_devices"] == 2
    assert {item["id"] for item in snapshot["devices"]} == {"ig-xv-01", "lox-xv-26"}
    assert all(item["isActive"] is True for item in snapshot["devices"])
