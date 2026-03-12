# # The serial port that the controller software is on
# sender = "/dev/ttyACM0"
# # The serial port the dummy sensor is on
# receiver = "/dev/ttyACM1"
# # The bitrate to use on the CAN bus
# bitrate = 1000000

# # The sensors and actuators
# devices = (
#     # {'name': 'Generic Sensor 1',   'class': 'GenericSensor',   'display': 'SensorRow',       'address': 0x64},
#     # {'name': 'Thermocouple 1',     'class': 'Thermocouple',    'display': 'ThermocoupleRow', 'address': 0x65},
#     # {'name': 'Generic Actuator 1', 'class': 'GenericActuator', 'display': 'ActuatorRow',     'address': 0x66},
#     # {'name': 'Fake Solenoid 1',    'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x67},
#     # {'name': 'Solenoid 1 (gen)',   'class': 'Solenoid',        'display': 'ActuatorRow',     'address': 0x67},
#     # {'name': 'Generic Sensor 2',   'class': 'GenericSensor',   'display': 'None',            'address': 0x64},
#     {'name': 'n2_purge',           'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x70, "config": {"inverted": True}},
#     {'name': 'n2_ipa',             'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x71},
#     {'name': 'n2_lox',             'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x72},
#     {'name': 'ipa_liquid',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x73},
#     {'name': '12V_test',           'class': 'GenericActuator', 'display': 'ActuatorRow',     'address': 0x77},
#     {'name': 'lox_liquid',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x80},
#     {'name': '24V_test',           'class': 'GenericActuator', 'display': 'ActuatorRow',     'address': 0x87},
#     # {'name': 'Solenoid 4',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x74},
#     # {'name': 'Solenoid 5',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x75},
#     # {'name': 'Solenoid 6',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x76},
#     # {'name': 'Solenoid 7',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x77},
# )








"""Device schema for the SCADA redesign


Fields

1. id
A unique and stable device identifier.
This should match the SVG / P&ID naming as closely as possible, so the software can reliably map UI elements to devices.

Example:
'id': 'IG-PSV-42'

2. name
A human-readable display name.
This is meant for the GUI and for developers/operators who should not have to read raw tag-style IDs everywhere.

Example:
'name': 'IG Pressure Safety Valve 42'

3. deviceType
The software-side device type.
This describes what backend device class or logic family the device belongs to.

Examples:
'deviceType': 'GenericSensor'
'deviceType': 'GenericActuator'
'deviceType': 'Solenoid'
'deviceType': 'Thermocouple'

4. deviceGroup
The engineering/device family grouping.
This is the domain-specific group the device belongs to, such as PT, XV, PSV, etc.
This is different from deviceType: multiple engineering groups may share the same backend device type.

Examples:
'deviceGroup': 'PT'
'deviceGroup': 'XV'
'deviceGroup': 'PSV'

5. deviceSystems
The system or systems this device belongs to.
This is a list because some devices may belong to more than one system.

Examples:
'deviceSystems': ['IG']
'deviceSystems': ['LOX']
'deviceSystems': ['IG', 'LOX']

6. address
The hardware / bus address of the device.
If the address is currently unknown, it can default to 0x000.

Example:
'address': 0x000

7. hasElectricalIO
Whether the device has electrical signal input/output that the software can read and/or interact with.
This is used to distinguish signal-based devices from purely mechanical devices.

Examples:
'hasElectricalIO': True
'hasElectricalIO': False

Typical interpretation:
- PT / TT / LC / XV -> True
- PSV / CV / HV / PC -> False

8. isControllable
Whether the software should provide control buttons for this device.
This is separate from hasElectricalIO because a device may have readable electrical signals without being software-controllable.

Examples:
'isControllable': True
'isControllable': False

Typical interpretation:
- XV -> True
- PT / TT / LC -> False
- PSV / CV / HV / PC -> False

9. widgetType
The UI widget category used when this device is displayed in the workspace.
This does not mean graph-only. It means what kind of UI component should represent the device.

Examples:
'widgetType': 'sensor'
'widgetType': 'solenoid'
'widgetType': 'mechanical'
'widgetType': 'thermocouple'

10. isActive
Whether the device should appear in the current active device library.
This is a configuration-level flag, not a runtime online/offline status.

Examples:
'isActive': True
'isActive': False
"""



# The serial port that the controller software is on
sender = "/dev/ttyACM0"
# The serial port the dummy sensor is on
receiver = "/dev/ttyACM1"
# The bitrate to use on the CAN bus
bitrate = 1000000

# The sensors and actuators
devices = (
    # =========================================================
    # Devices with signal
    # =========================================================

    # Weight cells
    {
        'id': 'LC1',
        'name': 'Weight Cell 1',
        'deviceType': 'GenericSensor',
        'deviceGroup': 'LC',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': True,
        'isControllable': False,
        'widgetType': 'sensor',
        'isActive': True,
    },
    {
        'id': 'LC2',
        'name': 'Weight Cell 2',
        'deviceType': 'GenericSensor',
        'deviceGroup': 'LC',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': True,
        'isControllable': False,
        'widgetType': 'sensor',
        'isActive': True,
    },
    {
        'id': 'LC3',
        'name': 'Weight Cell 3',
        'deviceType': 'GenericSensor',
        'deviceGroup': 'LC',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': True,
        'isControllable': False,
        'widgetType': 'sensor',
        'isActive': True,
    },
    {
        'id': 'LC4',
        'name': 'Weight Cell 4',
        'deviceType': 'GenericSensor',
        'deviceGroup': 'LC',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': True,
        'isControllable': False,
        'widgetType': 'sensor',
        'isActive': True,
    },

    # Pressure transmitters
    {
        'id': 'PT41',
        'name': 'Pressure Transmitter 41',
        'deviceType': 'GenericSensor',
        'deviceGroup': 'PT',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': True,
        'isControllable': False,
        'widgetType': 'sensor',
        'isActive': True,
    },
    {
        'id': 'PT42',
        'name': 'Pressure Transmitter 42',
        'deviceType': 'GenericSensor',
        'deviceGroup': 'PT',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': True,
        'isControllable': False,
        'widgetType': 'sensor',
        'isActive': True,
    },
    {
        'id': 'PT43',
        'name': 'Pressure Transmitter 43',
        'deviceType': 'GenericSensor',
        'deviceGroup': 'PT',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': True,
        'isControllable': False,
        'widgetType': 'sensor',
        'isActive': True,
    },
    {
        'id': 'PT44',
        'name': 'Pressure Transmitter 44',
        'deviceType': 'GenericSensor',
        'deviceGroup': 'PT',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': True,
        'isControllable': False,
        'widgetType': 'sensor',
        'isActive': True,
    },

    # Temperature transmitters (placeholder; not in SVG yet)
    {
        'id': 'TT1',
        'name': 'Temperature Transmitter 1',
        'deviceType': 'Thermocouple',
        'deviceGroup': 'TT',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': True,
        'isControllable': False,
        'widgetType': 'thermocouple',
        'isActive': False,
    },
    {
        'id': 'TT2',
        'name': 'Temperature Transmitter 2',
        'deviceType': 'Thermocouple',
        'deviceGroup': 'TT',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': True,
        'isControllable': False,
        'widgetType': 'thermocouple',
        'isActive': False,
    },

    # Solenoid valves
    {
        'id': 'IG-XV-24',
        'name': 'IG Solenoid Valve 24',
        'deviceType': 'Solenoid',
        'deviceGroup': 'XV',
        'deviceSystems': ['IG'],
        'address': 0x000,
        'hasElectricalIO': True,
        'isControllable': True,
        'widgetType': 'solenoid',
        'isActive': True,
    },
    {
        'id': 'IG-XV-27',
        'name': 'IG Solenoid Valve 27',
        'deviceType': 'Solenoid',
        'deviceGroup': 'XV',
        'deviceSystems': ['IG'],
        'address': 0x000,
        'hasElectricalIO': True,
        'isControllable': True,
        'widgetType': 'solenoid',
        'isActive': True,
    },
    {
        'id': 'IPA-XV-23',
        'name': 'IPA Solenoid Valve 23',
        'deviceType': 'Solenoid',
        'deviceGroup': 'XV',
        'deviceSystems': ['IPA'],
        'address': 0x000,
        'hasElectricalIO': True,
        'isControllable': True,
        'widgetType': 'solenoid',
        'isActive': True,
    },
    {
        'id': 'IPA-XV-25',
        'name': 'IPA Solenoid Valve 25',
        'deviceType': 'Solenoid',
        'deviceGroup': 'XV',
        'deviceSystems': ['IPA'],
        'address': 0x000,
        'hasElectricalIO': True,
        'isControllable': True,
        'widgetType': 'solenoid',
        'isActive': True,
    },
    {
        'id': 'LOX-XV-26',
        'name': 'LOX Solenoid Valve 26',
        'deviceType': 'Solenoid',
        'deviceGroup': 'XV',
        'deviceSystems': ['LOX'],
        'address': 0x000,
        'hasElectricalIO': True,
        'isControllable': True,
        'widgetType': 'solenoid',
        'isActive': True,
    },

    # =========================================================
    # Mechanical only (no signal, purely placeholder)
    # =========================================================

    # Physical watches
    {
        'id': 'IG-PC-21',
        'name': 'IG Physical Watch 21',
        'deviceType': 'GenericSensor',
        'deviceGroup': 'PC',
        'deviceSystems': ['IG'],
        'address': 0x000,
        'hasElectricalIO': False,
        'isControllable': False,
        'widgetType': 'mechanical',
        'isActive': True,
    },
    {
        'id': 'IG-PC-22',
        'name': 'IG Physical Watch 22',
        'deviceType': 'GenericSensor',
        'deviceGroup': 'PC',
        'deviceSystems': ['IG'],
        'address': 0x000,
        'hasElectricalIO': False,
        'isControllable': False,
        'widgetType': 'mechanical',
        'isActive': True,
    },

    # Check valves
    {
        'id': 'CV-011',
        'name': 'Check Valve 011',
        'deviceType': 'GenericActuator',
        'deviceGroup': 'CV',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': False,
        'isControllable': False,
        'widgetType': 'mechanical',
        'isActive': True,
    },
    {
        'id': 'CV-012',
        'name': 'Check Valve 012',
        'deviceType': 'GenericActuator',
        'deviceGroup': 'CV',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': False,
        'isControllable': False,
        'widgetType': 'mechanical',
        'isActive': True,
    },
    {
        'id': 'CV-013',
        'name': 'Check Valve 013',
        'deviceType': 'GenericActuator',
        'deviceGroup': 'CV',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': False,
        'isControllable': False,
        'widgetType': 'mechanical',
        'isActive': True,
    },
    {
        'id': 'CV-014',
        'name': 'Check Valve 014',
        'deviceType': 'GenericActuator',
        'deviceGroup': 'CV',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': False,
        'isControllable': False,
        'widgetType': 'mechanical',
        'isActive': True,
    },

    # Globe valves
    {
        'id': 'HV-036',
        'name': 'Globe Valve 036',
        'deviceType': 'GenericActuator',
        'deviceGroup': 'HV',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': False,
        'isControllable': False,
        'widgetType': 'mechanical',
        'isActive': True,
    },
    {
        'id': 'HV-039',
        'name': 'Globe Valve 039',
        'deviceType': 'GenericActuator',
        'deviceGroup': 'HV',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': False,
        'isControllable': False,
        'widgetType': 'mechanical',
        'isActive': True,
    },
    {
        'id': 'HV-040',
        'name': 'Globe Valve 040',
        'deviceType': 'GenericActuator',
        'deviceGroup': 'HV',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': False,
        'isControllable': False,
        'widgetType': 'mechanical',
        'isActive': True,
    },
    {
        'id': 'HV-051',
        'name': 'Globe Valve 051',
        'deviceType': 'GenericActuator',
        'deviceGroup': 'HV',
        'deviceSystems': [],
        'address': 0x000,
        'hasElectricalIO': False,
        'isControllable': False,
        'widgetType': 'mechanical',
        'isActive': True,
    },

    # Pressure safety valves
    {
        'id': 'IG-PSV-31',
        'name': 'IG Pressure Safety Valve 31',
        'deviceType': 'GenericActuator',
        'deviceGroup': 'PSV',
        'deviceSystems': ['IG'],
        'address': 0x000,
        'hasElectricalIO': False,
        'isControllable': False,
        'widgetType': 'mechanical',
        'isActive': True,
    },
    {
        'id': 'IG-PSV-32',
        'name': 'IG Pressure Safety Valve 32',
        'deviceType': 'GenericActuator',
        'deviceGroup': 'PSV',
        'deviceSystems': ['IG'],
        'address': 0x000,
        'hasElectricalIO': False,
        'isControllable': False,
        'widgetType': 'mechanical',
        'isActive': True,
    },
    {
        'id': 'IG-PSV-42',
        'name': 'IG Pressure Safety Valve 42',
        'deviceType': 'GenericActuator',
        'deviceGroup': 'PSV',
        'deviceSystems': ['IG'],
        'address': 0x000,
        'hasElectricalIO': False,
        'isControllable': False,
        'widgetType': 'mechanical',
        'isActive': True,
    },
)