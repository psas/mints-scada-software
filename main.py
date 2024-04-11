import sys
from PyQt5.QtWidgets import QApplication
import importlib

from nexus import Bus, BusRider, GenericSensor, GenericActuator
from gui import MainWindow, DeviceRow, AutoPoller, AutoPollerRow

import settings

baseaddr = 0x64

# Should be compatable with any slcan CANBus interface on Linux

# Set up all the things
with Bus(settings.sender, settings.bitrate, dbgprint=False) as bus:
    app = QApplication(sys.argv)
    window = MainWindow()

    for deviceDesc in settings.devices:
        # We don't know what type the device is, so try a bunch of devices and see if we can find it
        deviceClass = None
        devicePrefix = None
        for prefix in ["sensors", "actuators", "nexus"]:
            try:
                m = importlib.import_module(prefix)
                deviceClass = getattr(m,  deviceDesc["class"])
                break
            except Exception as e:
                continue
        # Check if we found the class
        if deviceClass is None:
            raise ImportError(f"Cannot find a device of type {deviceDesc['class']} to add")
        # Make sure the class is an allowable class
        if not issubclass(deviceClass, BusRider):
            raise ValueError(f"Device {deviceClass.__name__} must extend BusRider")
        # Initialize the device
        device = deviceClass(deviceDesc["address"], deviceDesc["name"])
        bus.addRider(device)
        
        # Find the display for the device
        if deviceDesc["display"] is not None and deviceDesc["display"] != 'None':
            deviceDisplayClass = None
            # Search for the class
            for prefix in ["sensorgui", "actuatorgui"]:
                try:
                    m = importlib.import_module(prefix)
                    deviceDisplayClass = getattr(m, deviceDesc["display"])
                except Exception as e:
                    continue
            # Check if we actually found a class
            if deviceDisplayClass is None:
                raise ImportError(f"Cannot find a display of type {deviceDesc['display']} to add")
            # Make sure the class is an allowable class
            if not issubclass(deviceDisplayClass, DeviceRow):
                raise ValueError(f"Device {deviceDisplayClass.__name__} must extend DeviceRow")
            display = deviceDisplayClass(device)
            window.mainLayout.addLayout(display)
    
    window.mainLayout.addStretch()
    
    with AutoPoller(bus=bus, interval=0.5) as ap:

        apr = AutoPollerRow(ap)
        window.mainLayout.addLayout(apr)

        window.show()
        app.exec()