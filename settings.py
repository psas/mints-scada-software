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
    {'name': 'eng_purge',          'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x70, "args": {"inverted": True}},
    {'name': 'ipa_purge',          'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x71},
    {'name': 'lox_purge',          'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x72},
    {'name': 'ipa_liquid',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x73},
    {'name': 'Solenoid 4',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x74},
    {'name': 'Solenoid 5',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x75},
    {'name': 'Solenoid 6',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x76},
    {'name': 'Solenoid 7',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x77},
)