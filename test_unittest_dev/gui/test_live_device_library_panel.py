from __future__ import annotations

import pytest


pytestmark = [pytest.mark.gui, pytest.mark.usefixtures("qapp")]



def _device(device_id: str, *, is_active: bool, has_electrical_io: bool, systems: list[str] | None = None):
    return {
        "id": device_id,
        "name": f"Device {device_id}",
        "deviceType": "GenericSensor" if has_electrical_io else "GenericActuator",
        "deviceGroup": "XV" if is_active else "PC",
        "deviceSystems": list(systems or ["IG"]),
        "address": 0x10,
        "hasElectricalIO": has_electrical_io,
        "isControllable": True,
        "widgetType": "sensor" if has_electrical_io else "mechanical",
        "isActive": is_active,
    }



def test_device_library_panel_places_isactive_true_devices_into_visible_active_sections(qapp):
    from gui.controller_window import DeviceLibraryPanel

    panel = DeviceLibraryPanel()
    panel.add_device(_device("ig-xv-01", is_active=True, has_electrical_io=True, systems=["IG"]))
    panel.add_device(_device("lox-xv-26", is_active=True, has_electrical_io=False, systems=["LOX"]))
    panel.add_device(_device("ig-pc-01", is_active=False, has_electrical_io=False, systems=["IG"]))
    qapp.processEvents()

    assert "ig-xv-01" in panel.active_signal_tree._device_items
    assert "lox-xv-26" in panel.active_mechanical_tree._device_items
    assert "ig-pc-01" in panel.inactive_tree._device_items
    assert "ig-xv-01" not in panel.inactive_tree._device_items
    assert "lox-xv-26" not in panel.inactive_tree._device_items
