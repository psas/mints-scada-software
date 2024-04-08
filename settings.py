# The serial port that the controller is on
sender = "/dev/ttyACM1"
# The serial port the dummy sensor is on
receiver = "/dev/ttyACM2"
# The bitrate to use on the CAN bus
bitrate = 1000000

# The sensors and actuators
things = (
    {'name': 'Generic Sensor 1',   'class': 'GenericSensor',   'display': 'SensorRow',       'address': 0x64},
    {'name': 'Thermocouple 1',     'class': 'Thermocouple',    'display': 'ThermocoupleRow', 'address': 0x65},
    {'name': 'Generic Actuator 1', 'class': 'GenericActuator', 'display': 'ActuatorRow',     'address': 0x66},
    {'name': 'Solenoid 1',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x67},
    {'name': 'Generic Sensor 2',   'class': 'GenericSensor',   'display': 'None',            'address': 0x64},
    {'name': 'Solenoid 2',         'class': 'Solenoid',        'display': 'SolenoidRow',     'address': 0x67},
)