import sys
from PyQt5.QtWidgets import QApplication
import importlib

from nexus import Bus, BusRider, GenericSensor, GenericActuator
from gui import MainWindow, DeviceRow, AutoPoller, AutoPollerRow

import settings

# Should be compatable with any slcan CANBus interface on Linux

import logging
log = logging.getLogger(__name__)

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(name)-12.12s] [%(levelname)-5.5s]  %(message)s",
        handlers=[
            logging.FileHandler("log/debug.log"),
            logging.StreamHandler()
        ]
    )
    log.debug("Hi!")
    print("Should have HI'd just a moment ago")

    # Set up all the things
    with Bus(settings.sender, settings.bitrate, packetprinting=False, packetlogging=False) as bus:
        app = QApplication(sys.argv)
        window = MainWindow()

        # Load all devices from settings
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
            isVisibleOnList = deviceDesc["display"] is not None and deviceDesc["display"] != 'None'
            if isVisibleOnList:
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
                window.listtab.layout.addLayout(display)
            window.graph.addSensor(device, isVisibleOnList)
        
        window.listtab.layout.addStretch()
        
        with AutoPoller(bus=bus, interval=0.5, autostart=False) as ap:

            apr = AutoPollerRow(ap)
            window.mainlayout.addLayout(apr)

            window.show()
            app.exec()