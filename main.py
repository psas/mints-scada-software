import sys
from PyQt5.QtWidgets import QApplication
import importlib

from nexus import Bus, BusRider, GenericSensor, GenericActuator
from gui import MainWindow, DeviceRow, AutoPoller, AutoPollerRow, QLoggingHandler

import settings

# Should be compatable with any slcan CANBus interface on Linux

import logging
log = logging.getLogger(__name__)

if __name__ == '__main__':
    formatstr = "%(asctime)s [%(name)-16.16s] [%(levelname)-5.5s]  %(message)s"
    consolehandler = QLoggingHandler()
    consolehandler.setFormatter(logging.Formatter(formatstr))
    logging.basicConfig(
        level=logging.DEBUG,
        format=formatstr,
        handlers=[
            logging.FileHandler("log/debug.log"),
            logging.StreamHandler(),
            consolehandler
        ]
    )
    log.debug("Hi!")

    # Set up all the things
    with Bus(settings.sender, settings.bitrate, packetprinting=False, packetlogging=False) as bus:
        with AutoPoller(bus=bus, interval=0.5, autostart=False) as ap:
            app = QApplication(sys.argv)
            window = MainWindow(loghandler=consolehandler, autopoller=ap)

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
                display = None
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
                window.addDevice(device, display)
            
            window.show()
            app.exec()