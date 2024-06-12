# The serial port that the controller software is on
sender = "/dev/ttyACM0"
# The serial port the dummy sensor is on
receiver = "/dev/ttyACM1"
# The bitrate to use on the CAN bus
bitrate = 1000000

# The sensors and actuators
devices = (
    {'name': 'Generic Sensor 1',   'class': 'GenericSensor',   'display': 'SensorRow',       'address': 0x64},
    {'name': 'Thermocouple 1',     'class': 'Thermocouple',    'display': 'ThermocoupleRow', 'address': 0x65},
    {'name': 'Generic Actuator 1', 'class': 'GenericActuator', 'display': 'ActuatorRow',     'address': 0x66},
    {'name': 'Solenoid 1',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x67},
    {'name': 'Solenoid 1 (gen)',   'class': 'Solenoid',        'display': 'ActuatorRow',     'address': 0x67},
    {'name': 'Generic Sensor 2',   'class': 'GenericSensor',   'display': 'None',            'address': 0x64},
    {'name': 'Real Gen. Actuator', 'class': 'GenericActuator', 'display': 'ActuatorRow',     'address': 0x70},
)