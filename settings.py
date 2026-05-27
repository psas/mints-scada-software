# The serial port that the controller software is on
sender = "/dev/ttyACM0"
# The serial port the dummy sensor is on
# receiver = "/dev/ttyACM1"
# The bitrate to use on the CAN bus
bitrate = 1000000

# The sensors and actuators
devices = (
    {'name': 'MCP Ch 1',   'class': 'MCP346x',   'display': 'MCP346xRow',       'address': 0x08, "config": {"autopoll": True, "ref": 2.39}},
    {'name': 'MCP Ch 2',   'class': 'MCP346x',   'display': 'MCP346xRow',       'address': 0x09, "config": {"autopoll": True, "ref": 2.39}},
    {'name': 'Generic Sensor 3',   'class': 'GenericSensor',   'display': 'SensorRow',       'address': 0x0A, "config": {"autopoll": False}},
    {'name': 'Generic Sensor 4',   'class': 'GenericSensor',   'display': 'SensorRow',       'address': 0x0B, "config": {"autopoll": False}},
    {'name': 'Generic Sensor 5',   'class': 'GenericSensor',   'display': 'SensorRow',       'address': 0x0C, "config": {"autopoll": False}},
    {'name': 'Generic Sensor 6',   'class': 'GenericSensor',   'display': 'SensorRow',       'address': 0x18, "config": {"autopoll": False}},
    # {'name': 'Thermocouple 1',     'class': 'Thermocouple',    'display': 'ThermocoupleRow', 'address': 0x65},
    {'name': 'Generic Actuator 1', 'class': 'GenericActuator', 'display': 'ActuatorRow',     'address': 0x66, "config": {"autopoll": False}},
    # {'name': 'Fake Solenoid 1',    'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x67},
    # {'name': 'Solenoid 1 (gen)',   'class': 'Solenoid',        'display': 'ActuatorRow',     'address': 0x67},
    # {'name': 'Generic Sensor 2',   'class': 'GenericSensor',   'display': 'None',            'address': 0x64},
    # {'name': 'n2_purge',           'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x70, "config": {"inverted": True}},
    # {'name': 'n2_ipa',             'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x71},
    # {'name': 'n2_lox',             'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x72},
    # {'name': 'ipa_liquid',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x73},
    # {'name': '12V_test',           'class': 'GenericActuator', 'display': 'ActuatorRow',     'address': 0x77},
    # {'name': 'lox_liquid',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x80},
    # {'name': '24V_test',           'class': 'GenericActuator', 'display': 'ActuatorRow',     'address': 0x87},
    # {'name': 'Solenoid 4',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x74},
    # {'name': 'Solenoid 5',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x75},
    # {'name': 'Solenoid 6',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x76},
    # {'name': 'Solenoid 7',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x77},
)