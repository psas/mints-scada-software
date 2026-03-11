# The serial port that the controller software is on
sender = "/dev/ttyACM0"
# The serial port the dummy sensor is on
receiver = "/dev/ttyACM1"
# The bitrate to use on the CAN bus
bitrate = 1000000

# The sensors and actuators
devices = (
    # {'name': 'Generic Sensor 1',   'class': 'GenericSensor',   'display': 'SensorRow',       'address': 0x64},
    # {'name': 'Thermocouple 1',     'class': 'Thermocouple',    'display': 'ThermocoupleRow', 'address': 0x65},
    # {'name': 'Generic Actuator 1', 'class': 'GenericActuator', 'display': 'ActuatorRow',     'address': 0x66},
    # {'name': 'Fake Solenoid 1',    'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x67},
    # {'name': 'Solenoid 1 (gen)',   'class': 'Solenoid',        'display': 'ActuatorRow',     'address': 0x67},
    # {'name': 'Generic Sensor 2',   'class': 'GenericSensor',   'display': 'None',            'address': 0x64},
    {'name': 'n2_purge',           'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x70, "config": {"inverted": True}},
    {'name': 'n2_ipa',             'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x71},
    {'name': 'n2_lox',             'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x72},
    {'name': 'ipa_liquid',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x73},
    {'name': '12V_test',           'class': 'GenericActuator', 'display': 'ActuatorRow',     'address': 0x77},
    {'name': 'lox_liquid',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x80},
    {'name': '24V_test',           'class': 'GenericActuator', 'display': 'ActuatorRow',     'address': 0x87},
    # {'name': 'Solenoid 4',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x74},
    # {'name': 'Solenoid 5',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x75},
    # {'name': 'Solenoid 6',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x76},
    # {'name': 'Solenoid 7',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x77},
)


# # The serial port that the controller software is on
# sender = "/dev/ttyACM0"
# # The serial port the dummy sensor is on
# receiver = "/dev/ttyACM1"
# # The bitrate to use on the CAN bus
# bitrate = 1000000

# # The sensors and actuators
# devices = (
#     # =========================================================
#     # Devices with signal
#     # =========================================================

#     # Weight cells
#     {'id': 'LC1', 'name': 'Weight Cell 1', 'class': 'GenericSensor', 'display': 'SensorRow', 'address': 0x000},
#     {'id': 'LC2', 'name': 'Weight Cell 2', 'class': 'GenericSensor', 'display': 'SensorRow', 'address': 0x000},
#     {'id': 'LC3', 'name': 'Weight Cell 3', 'class': 'GenericSensor', 'display': 'SensorRow', 'address': 0x000},
#     {'id': 'LC4', 'name': 'Weight Cell 4', 'class': 'GenericSensor', 'display': 'SensorRow', 'address': 0x000},

#     # Pressure transmitters
#     {'id': 'PT41', 'name': 'Pressure Transmitter 41', 'class': 'GenericSensor', 'display': 'SensorRow', 'address': 0x000},
#     {'id': 'PT42', 'name': 'Pressure Transmitter 42', 'class': 'GenericSensor', 'display': 'SensorRow', 'address': 0x000},
#     {'id': 'PT43', 'name': 'Pressure Transmitter 43', 'class': 'GenericSensor', 'display': 'SensorRow', 'address': 0x000},
#     {'id': 'PT44', 'name': 'Pressure Transmitter 44', 'class': 'GenericSensor', 'display': 'SensorRow', 'address': 0x000},

#     # Temperature transmitters (placeholder; not in SVG yet)
#     {'id': 'TT1', 'name': 'Temperature Transmitter 1', 'class': 'Thermocouple', 'display': 'ThermocoupleRow', 'address': 0x000},
#     {'id': 'TT2', 'name': 'Temperature Transmitter 2', 'class': 'Thermocouple', 'display': 'ThermocoupleRow', 'address': 0x000},

#     # Solenoid valves
#     {'id': 'IG-XV-24', 'name': 'IG Solenoid Valve 24', 'class': 'Solenoid', 'display': 'SolenoidRow', 'address': 0x000},
#     {'id': 'IG-XV-27', 'name': 'IG Solenoid Valve 27', 'class': 'Solenoid', 'display': 'SolenoidRow', 'address': 0x000},
#     {'id': 'IPA-XV-23', 'name': 'IPA Solenoid Valve 23', 'class': 'Solenoid', 'display': 'SolenoidRow', 'address': 0x000},
#     {'id': 'IPA-XV-25', 'name': 'IPA Solenoid Valve 25', 'class': 'Solenoid', 'display': 'SolenoidRow', 'address': 0x000},
#     {'id': 'LOX-XV-26', 'name': 'LOX Solenoid Valve 26', 'class': 'Solenoid', 'display': 'SolenoidRow', 'address': 0x000},




#     # =========================================================
#     # Mechanical only (no signal, purely placeholder)
#     # =========================================================

#     # Physical watches
#     {'id': 'IG-PC-21', 'name': 'IG Physical Watch 21', 'class': 'GenericSensor', 'display': 'None', 'address': 0x000},
#     {'id': 'IG-PC-22', 'name': 'IG Physical Watch 22', 'class': 'GenericSensor', 'display': 'None', 'address': 0x000},

#     # Check valves
#     {'id': 'CV-011', 'name': 'Check Valve 011', 'class': 'GenericActuator', 'display': 'None', 'address': 0x000},
#     {'id': 'CV-012', 'name': 'Check Valve 012', 'class': 'GenericActuator', 'display': 'None', 'address': 0x000},
#     {'id': 'CV-013', 'name': 'Check Valve 013', 'class': 'GenericActuator', 'display': 'None', 'address': 0x000},
#     {'id': 'CV-014', 'name': 'Check Valve 014', 'class': 'GenericActuator', 'display': 'None', 'address': 0x000},

#     # Globe valves
#     {'id': 'HV-036', 'name': 'Globe Valve 036', 'class': 'GenericActuator', 'display': 'None', 'address': 0x000},
#     {'id': 'HV-039', 'name': 'Globe Valve 039', 'class': 'GenericActuator', 'display': 'None', 'address': 0x000},
#     {'id': 'HV-040', 'name': 'Globe Valve 040', 'class': 'GenericActuator', 'display': 'None', 'address': 0x000},
#     {'id': 'HV-051', 'name': 'Globe Valve 051', 'class': 'GenericActuator', 'display': 'None', 'address': 0x000},

#     # Pressure safety valves
#     {'id': 'IG-PSV-31', 'name': 'IG Pressure Safety Valve 31', 'class': 'GenericActuator', 'display': 'None', 'address': 0x000},
#     {'id': 'IG-PSV-32', 'name': 'IG Pressure Safety Valve 32', 'class': 'GenericActuator', 'display': 'None', 'address': 0x000},
#     {'id': 'IG-PSV-42', 'name': 'IG Pressure Safety Valve 42', 'class': 'GenericActuator', 'display': 'None', 'address': 0x000},



# )