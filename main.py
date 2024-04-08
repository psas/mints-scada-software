import sys
from PyQt5.QtWidgets import QApplication
import importlib

from nexus import Bus, BusRider, GenericSensor, GenericActuator
from gui import MainWindow, ThingRow

import settings

baseaddr = 0x64

# Should be compatable with any slcan CANBus interface on Linux
with Bus(settings.sender, settings.bitrate, dbgprint=False) as bus:
    app = QApplication(sys.argv)
    window = MainWindow()

    for thingDesc in settings.things:
        # We don't know what type the thing is, so try a bunch of things and see if we can find it
        thingClass = None
        thingPrefix = None
        for prefix in ["sensors", "actuators", "nexus"]:
            try:
                m = importlib.import_module(prefix)
                thingClass = getattr(m,  thingDesc["class"])
                break
            except Exception as e:
                continue
        # Check if we found the class
        if thingClass is None:
            raise ImportError(f"Cannot find a thing of type {thingDesc['class']} to add")
        # Make sure the class is an allowable class
        if not issubclass(thingClass, BusRider):
            raise ValueError(f"Thing {thingClass.__name__} must extend BusRider")
        # Initialize the thing
        thing = thingClass(thingDesc["address"], thingDesc["name"])
        bus.addRider(thing)
        
        # Find the display for the thing
        if thingDesc["display"] is not None and thingDesc["display"] != 'None':
            thingDisplayClass = None
            # Search for the class
            for prefix in ["sensorgui", "actuatorgui"]:
                try:
                    m = importlib.import_module(prefix)
                    thingDisplayClass = getattr(m, thingDesc["display"])
                except Exception as e:
                    continue
            # Check if we actually found a class
            if thingDisplayClass is None:
                raise ImportError(f"Cannot find a display of type {thingDesc['display']} to add")
            # Make sure the class is an allowable class
            if not issubclass(thingDisplayClass, ThingRow):
                raise ValueError(f"Thing {thingDisplayClass.__name__} must extend ThingRow")
            display = thingDisplayClass(thing)
            window.mainLayout.addLayout(display)

    window.mainLayout.addStretch()

    window.show()
    sys.exit(app.exec())