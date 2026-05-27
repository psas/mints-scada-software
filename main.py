import sys
from PyQt5.QtWidgets import QApplication
import importlib
import os

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
    if not os.path.isdir("log"):
        os.mkdir("log")
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

    slcanport = settings.sender

    if len(sys.argv) >= 2:
        slcanport = sys.argv[1]

    if not os.path.exists(slcanport):
        print(f"It looks like the specified slcan interface {slcanport} doesn't exist.")
        prefixed = [entry for entry in os.listdir('/dev/') if entry.startswith("ttyACM")]
        if len(prefixed) == 0:
            print("No options found. You can still type the correct path, or stop the program and plug it in.")
        else:
            print("Options:")
            for i,poss in enumerate(prefixed):
                print(f"\t{i}: {poss}")
            print("Type either the number of the option, or the path to the interface")
            iv = input("> ")
            if len(iv) == 0:
                slcanport = ""
            else:
                try:
                    slcanport = "/dev/" + prefixed[int(iv)]
                except ValueError:
                    slcanport = iv

        if not os.path.exists(slcanport):
            log.fatal(f"CAN port {slcanport} not found, aborting.")
            exit()

        log.info("reselected slcan port " + slcanport)

    # Set up all the things
    with Bus(slcanport, settings.bitrate, packetprinting=False, packetlogging=False) as bus:
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
                # Prepare device configuration
                config = deviceDesc["config"] if "config" in deviceDesc else {}
                # Initialize the device
                device = deviceClass(deviceDesc["address"], deviceDesc["name"], **config)
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
                    displayConfig = deviceDesc["displayConfig"] if "displayConfig" in deviceDesc else {}
                    display = deviceDisplayClass(device, **displayConfig)
                window.addDevice(device, display)
            
            window.show()
            app.exec()