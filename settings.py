"""settings.py

Define the static device catalog and shared device-schema helpers.

This module is the single source of truth for device metadata that is shared
across backend and GUI code. It provides:

- hardware/bus defaults used by live runtime startup
- ``LIVE_STARTUP_STATE`` seeds for one-time live valve state initialization
- the canonical device descriptor schema and validation rules
- the static ``devices`` catalog consumed by runtime inventory and GUI presentation layers
- catalog-derived helpers such as ``get_controllable_valve_ids``

All device IDs use the canonical lowercase-hyphenated format so they can match
backend/runtime identifiers and SCADA SVG element IDs.

Fields
------

1. id
   A unique and stable device identifier in lowercase-hyphenated form.
   Must match ``^[a-z0-9]+(-[a-z0-9]+)*$``.
   This matches the SVG element IDs so the software can reliably map
   UI elements to devices.

   Example:

       'id': 'ig-psv-42'

2. name
   A human-readable display name for the GUI and operators.

   Example:

       'name': 'IG Pressure Safety Valve 42'

3. deviceType
   The software-side device type / backend class family.

   Examples:

       'deviceType': 'GenericSensor'
       'deviceType': 'GenericActuator'
       'deviceType': 'Solenoid'
       'deviceType': 'Thermocouple'

4. deviceGroup
   The engineering/device family grouping (PT, XV, PSV, etc.).
   Different from deviceType: multiple engineering groups may share the
   same backend device type.

   Examples:

       'deviceGroup': 'PT'
       'deviceGroup': 'XV'
       'deviceGroup': 'PSV'

5. deviceSystems
   The system or systems this device belongs to. This is a **list**
   because a device may belong to more than one system. An empty list
   is valid for devices that are not tied to any particular system
   (e.g. weight cells).

   Examples:

       'deviceSystems': []
       'deviceSystems': ['IG']
       'deviceSystems': ['LOX']
       'deviceSystems': ['IG', 'LOX']

6. address
   The hardware / CAN bus address. Use ``0x000`` when unknown.

   Example:

       'address': 0x000

7. hasElectricalIO
   Whether the device has electrical signal I/O the software can read.

   Typical: PT / TT / LC / XV -> True; PSV / CV / HV / PC -> False.

8. isControllable
   Whether the software provides control buttons for this device.
   Separate from hasElectricalIO - a device may be readable without
   being software-controllable.

   Typical: XV -> True; everything else -> False.

9. widgetType
   The UI widget category: ``'sensor'``, ``'solenoid'``,
   ``'mechanical'``, ``'thermocouple'``.

10. isActive
    Whether the device appears in the current active device library.
    Configuration-level flag, not runtime online/offline status.
"""

from __future__ import annotations

import re
from typing import Any


#
# Hardware / bus configuration
#

# The serial port that the controller software is on
sender = "/dev/ttyACM0"
# The serial port the dummy sensor is on
receiver = "/dev/ttyACM1"
# The bitrate to use on the CAN bus
bitrate = 1000000


# ---------------------------------------------------------------------
# Live startup state seed
# ---------------------------------------------------------------------

# One-time software-side state seed applied when live hardware initializes.
# Keys are canonical device IDs; values are the expected startup valve state.
# This does NOT send commands to hardware - it only initializes runtime state
# so the operator sees correct XV positions immediately on live startup.
# Later command-driven state updates overwrite these normally. (Current XVs
# are blind-controlled with no position-feedback telemetry.)
LIVE_STARTUP_STATE: dict[str, str] = {
    "ipa-xv-23": "closed",
    "ig-xv-24": "closed",
    "ipa-xv-25": "closed",
    "lox-xv-26": "closed",
    "ig-xv-27": "open",
}


#
# Schema and ordering constants
#

# Explicit display ordering for device systems in the GUI.
SYSTEM_ORDER = ("IG", "IPA", "LOX")


#
# Device catalog
#

devices = (
    # =========================================================
    # Devices with signal
    # =========================================================
    # Weight cells
    {
        "id": "lc-1",
        "name": "Weight Cell 1",
        "deviceType": "GenericSensor",
        "deviceGroup": "LC",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": True,
        "isControllable": False,
        "widgetType": "sensor",
        "isActive": False,
    },
    {
        "id": "lc-2",
        "name": "Weight Cell 2",
        "deviceType": "GenericSensor",
        "deviceGroup": "LC",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": True,
        "isControllable": False,
        "widgetType": "sensor",
        "isActive": False,
    },
    {
        "id": "lc-3",
        "name": "Weight Cell 3",
        "deviceType": "GenericSensor",
        "deviceGroup": "LC",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": True,
        "isControllable": False,
        "widgetType": "sensor",
        "isActive": False,
    },
    {
        "id": "lc-4",
        "name": "Weight Cell 4",
        "deviceType": "GenericSensor",
        "deviceGroup": "LC",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": True,
        "isControllable": False,
        "widgetType": "sensor",
        "isActive": False,
    },
    # Pressure transmitters
    {
        "id": "pt-41",
        "name": "Pressure Transmitter 41",
        "deviceType": "GenericSensor",
        "deviceGroup": "PT",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": True,
        "isControllable": False,
        "widgetType": "sensor",
        "isActive": False,
    },
    {
        "id": "pt-42",
        "name": "Pressure Transmitter 42",
        "deviceType": "GenericSensor",
        "deviceGroup": "PT",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": True,
        "isControllable": False,
        "widgetType": "sensor",
        "isActive": False,
    },
    {
        "id": "pt-43",
        "name": "Pressure Transmitter 43",
        "deviceType": "GenericSensor",
        "deviceGroup": "PT",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": True,
        "isControllable": False,
        "widgetType": "sensor",
        "isActive": False,
    },
    {
        "id": "pt-44",
        "name": "Pressure Transmitter 44",
        "deviceType": "GenericSensor",
        "deviceGroup": "PT",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": True,
        "isControllable": False,
        "widgetType": "sensor",
        "isActive": False,
    },
    # Temperature transmitters (placeholder; not in SVG yet)
    {
        "id": "tt-1",
        "name": "Temperature Transmitter 1",
        "deviceType": "Thermocouple",
        "deviceGroup": "TT",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": True,
        "isControllable": False,
        "widgetType": "thermocouple",
        "isActive": False,
    },
    {
        "id": "tt-2",
        "name": "Temperature Transmitter 2",
        "deviceType": "Thermocouple",
        "deviceGroup": "TT",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": True,
        "isControllable": False,
        "widgetType": "thermocouple",
        "isActive": False,
    },
    # Solenoid valves
    {
        "id": "ig-xv-24",
        "name": "n2_lox (XV-24)",
        "deviceType": "Solenoid",
        "deviceGroup": "XV",
        "deviceSystems": ["IG"],
        "address": 0x77,
        "hasElectricalIO": True,
        "isControllable": True,
        "widgetType": "solenoid",
        "isActive": True,
    },
    {
        "id": "ig-xv-27",
        "name": "n2_purge (XV-27)",
        "deviceType": "Solenoid",
        "deviceGroup": "XV",
        "deviceSystems": ["IG"],
        "address": 0x70,
        "hasElectricalIO": True,
        "isControllable": True,
        "widgetType": "solenoid",
        "isActive": True,
        "config": {"inverted": True},
    },
    {
        "id": "ipa-xv-23",
        "name": "n2_ipa (XV-23)",
        "deviceType": "Solenoid",
        "deviceGroup": "XV",
        "deviceSystems": ["IPA"],
        "address": 0x72,
        "hasElectricalIO": True,
        "isControllable": True,
        "widgetType": "solenoid",
        "isActive": True,
    },
    {
        "id": "ipa-xv-25",
        "name": "ipa_liquid (XV-25)",
        "deviceType": "Solenoid",
        "deviceGroup": "XV",
        "deviceSystems": ["IPA"],
        "address": 0x71,
        "hasElectricalIO": True,
        "isControllable": True,
        "widgetType": "solenoid",
        "isActive": True,
    },
    {
        "id": "lox-xv-26",
        "name": "lox_liquid (XV-26)",
        "deviceType": "Solenoid",
        "deviceGroup": "XV",
        "deviceSystems": ["LOX"],
        "address": 0x82,
        "hasElectricalIO": True,
        "isControllable": True,
        "widgetType": "solenoid",
        "isActive": True,
    },
    {
        "id": "igniter",
        "name": "Igniter",
        "deviceType": "GenericActuator",
        "deviceGroup": "IGN",
        "deviceSystems": ["IG"],
        "address": 0x74,
        "hasElectricalIO": True,
        "isControllable": True,
        "widgetType": "solenoid",
        "isActive": True,
    },
    # =========================================================
    # Mechanical only (no signal, purely placeholder)
    # =========================================================
    # Physical watches
    {
        "id": "ig-pc-21",
        "name": "IG Physical Watch 21",
        "deviceType": "GenericSensor",
        "deviceGroup": "PC",
        "deviceSystems": ["IG"],
        "address": 0x000,
        "hasElectricalIO": False,
        "isControllable": False,
        "widgetType": "mechanical",
        "isActive": False,
    },
    {
        "id": "ig-pc-22",
        "name": "IG Physical Watch 22",
        "deviceType": "GenericSensor",
        "deviceGroup": "PC",
        "deviceSystems": ["IG"],
        "address": 0x000,
        "hasElectricalIO": False,
        "isControllable": False,
        "widgetType": "mechanical",
        "isActive": False,
    },
    # Check valves
    {
        "id": "cv-011",
        "name": "Check Valve 011",
        "deviceType": "GenericActuator",
        "deviceGroup": "CV",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": False,
        "isControllable": False,
        "widgetType": "mechanical",
        "isActive": False,
    },
    {
        "id": "cv-012",
        "name": "Check Valve 012",
        "deviceType": "GenericActuator",
        "deviceGroup": "CV",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": False,
        "isControllable": False,
        "widgetType": "mechanical",
        "isActive": False,
    },
    {
        "id": "cv-013",
        "name": "Check Valve 013",
        "deviceType": "GenericActuator",
        "deviceGroup": "CV",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": False,
        "isControllable": False,
        "widgetType": "mechanical",
        "isActive": False,
    },
    {
        "id": "cv-014",
        "name": "Check Valve 014",
        "deviceType": "GenericActuator",
        "deviceGroup": "CV",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": False,
        "isControllable": False,
        "widgetType": "mechanical",
        "isActive": False,
    },
    # Globe valves
    {
        "id": "hv-036",
        "name": "Globe Valve 036",
        "deviceType": "GenericActuator",
        "deviceGroup": "HV",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": False,
        "isControllable": False,
        "widgetType": "mechanical",
        "isActive": False,
    },
    {
        "id": "hv-039",
        "name": "Globe Valve 039",
        "deviceType": "GenericActuator",
        "deviceGroup": "HV",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": False,
        "isControllable": False,
        "widgetType": "mechanical",
        "isActive": False,
    },
    {
        "id": "hv-040",
        "name": "Globe Valve 040",
        "deviceType": "GenericActuator",
        "deviceGroup": "HV",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": False,
        "isControllable": False,
        "widgetType": "mechanical",
        "isActive": False,
    },
    {
        "id": "hv-051",
        "name": "Globe Valve 051",
        "deviceType": "GenericActuator",
        "deviceGroup": "HV",
        "deviceSystems": [],
        "address": 0x000,
        "hasElectricalIO": False,
        "isControllable": False,
        "widgetType": "mechanical",
        "isActive": False,
    },
    # Pressure safety valves
    {
        "id": "ig-psv-31",
        "name": "IG Pressure Safety Valve 31",
        "deviceType": "GenericActuator",
        "deviceGroup": "PSV",
        "deviceSystems": ["IG"],
        "address": 0x000,
        "hasElectricalIO": False,
        "isControllable": False,
        "widgetType": "mechanical",
        "isActive": False,
    },
    {
        "id": "ig-psv-32",
        "name": "IG Pressure Safety Valve 32",
        "deviceType": "GenericActuator",
        "deviceGroup": "PSV",
        "deviceSystems": ["IG"],
        "address": 0x000,
        "hasElectricalIO": False,
        "isControllable": False,
        "widgetType": "mechanical",
        "isActive": False,
    },
    {
        "id": "ig-psv-42",
        "name": "IG Pressure Safety Valve 42",
        "deviceType": "GenericActuator",
        "deviceGroup": "PSV",
        "deviceSystems": ["IG"],
        "address": 0x000,
        "hasElectricalIO": False,
        "isControllable": False,
        "widgetType": "mechanical",
        "isActive": False,
    },
)


#
# Catalog-derived helpers
#

# Every device descriptor in the ``devices`` tuple must contain these keys.
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

# Canonical device ID pattern: one or more lowercase-alphanumeric segments
# separated by hyphens (e.g. "ig-xv-24", "lc-1", "cv-011").
_DEVICE_ID_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def normalize_device_desc(device_desc: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize one raw device descriptor from ``devices``.

    The returned descriptor preserves the shared catalog schema used by the
    backend device registry and GUI-side presentation catalog. Validation is
    intentionally strict: required fields must exist, string and boolean fields
    must have the expected runtime types, ``deviceSystems`` must be an explicit
    list of strings, and the device ID must match the canonical lowercase-
    hyphenated format. The returned ``config`` mapping is copied into a plain
    ``dict`` even when the source descriptor omits it.

    Args:
        device_desc: Raw device descriptor dictionary from the static
            ``devices`` catalog.

    Returns:
        A normalized descriptor containing all required catalog fields plus a
        copied ``config`` dictionary. ``deviceSystems`` entries are stripped of
        surrounding whitespace.

    Raises:
        KeyError: One or more required device fields are missing.
        ValueError: ``id`` is missing, empty, or does not match the canonical
            lowercase-hyphenated device ID format.
        TypeError: A required string field is empty or not a string,
            ``deviceSystems`` is not a list of non-empty strings, a boolean
            field is not an actual ``bool``, or ``address`` is not a real
            integer value.
    """
    missing = [key for key in REQUIRED_DEVICE_FIELDS if key not in device_desc]
    if missing:
        raise KeyError(
            f"Device config is missing required fields: {missing}\nConfig: {device_desc}"
        )

    # --- id validation ---
    raw_id = device_desc["id"]
    if not isinstance(raw_id, str) or not raw_id:
        raise ValueError(f"Device id must be a non-empty string, got {raw_id!r}")
    if not _DEVICE_ID_RE.fullmatch(raw_id):
        raise ValueError(
            f"Device id {raw_id!r} does not match the canonical "
            f"lowercase-hyphenated format (e.g. 'ig-xv-24', 'lc-1')"
        )

    # --- required string fields ---
    for str_field in ("name", "deviceType", "deviceGroup", "widgetType"):
        val = device_desc[str_field]
        if not isinstance(val, str) or not val.strip():
            raise TypeError(
                f"{str_field} must be a non-empty string for device {raw_id!r}, "
                f"got {type(val).__name__}: {val!r}"
            )

    # --- deviceSystems validation ---
    # Must be an explicit list ([] is valid).  None, bare strings, and
    # tuples are rejected - write [] for no system membership.
    raw_systems = device_desc["deviceSystems"]
    if isinstance(raw_systems, str):
        raise TypeError(
            f"deviceSystems must be a list, not a bare string "
            f"{raw_systems!r} (for device {raw_id!r}). "
            f"Use ['{raw_systems}'] instead."
        )
    if not isinstance(raw_systems, list):
        raise TypeError(
            f"deviceSystems must be a list for device {raw_id!r}, "
            f"got {type(raw_systems).__name__}: {raw_systems!r}"
        )
    systems: list[str] = []
    for entry in raw_systems:
        if not isinstance(entry, str) or not entry.strip():
            raise TypeError(
                f"Each deviceSystems entry must be a non-empty string, "
                f"got {entry!r} (in device {raw_id!r})"
            )
        systems.append(entry.strip())

    # --- boolean fields (must be actual bool, not truthy coercion) ---
    for bool_field in ("hasElectricalIO", "isControllable", "isActive"):
        val = device_desc[bool_field]
        if not isinstance(val, bool):
            raise TypeError(
                f"{bool_field} must be a bool for device {raw_id!r}, "
                f"got {type(val).__name__}: {val!r}"
            )

    # --- address (must be a real int, not bool) ---
    raw_address = device_desc["address"]
    if not isinstance(raw_address, int) or isinstance(raw_address, bool):
        raise TypeError(
            f"address must be an int for device {raw_id!r}, "
            f"got {type(raw_address).__name__}: {raw_address!r}"
        )

    meta: dict[str, Any] = {
        "id": raw_id,
        "name": device_desc["name"],
        "deviceType": device_desc["deviceType"],
        "deviceGroup": device_desc["deviceGroup"],
        "deviceSystems": systems,
        "address": raw_address,
        "hasElectricalIO": device_desc["hasElectricalIO"],
        "isControllable": device_desc["isControllable"],
        "widgetType": device_desc["widgetType"],
        "isActive": device_desc["isActive"],
        "config": dict(device_desc.get("config", {})),
    }

    return meta


def get_controllable_valve_ids() -> tuple[str, ...]:
    """Return canonical IDs for active controllable XV devices.

    The result is derived directly from the static ``devices`` catalog and keeps
    the catalog declaration order. These IDs are used by SCADA and related GUI
    code as the base element IDs; interactive SVG control groups append the
    ``-control`` suffix.

    Returns:
        A tuple of canonical device IDs for devices whose catalog entries are
        grouped as ``XV`` and marked both controllable and active.
    """
    return tuple(
        d["id"]
        for d in devices
        if d.get("deviceGroup") == "XV"
        and d.get("isControllable") is True
        and d.get("isActive") is True
    )
