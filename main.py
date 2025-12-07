import sys
from PyQt5.QtWidgets import QApplication, QMessageBox
import importlib
import os
import json

from nexus import Bus, BusRider, GenericSensor, GenericActuator
from gui import MainWindow, DeviceRow, AutoPoller, AutoPollerRow, QLoggingHandler, ChecklistWindow

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

    # Create QApplication first (needed for checklist window)
    app = QApplication(sys.argv)

    # Show startup checklist
    checklist = ChecklistWindow(settings.sender)
    if checklist.exec_() != QMessageBox.Accepted:
        log.info("User cancelled startup checklist")
        sys.exit(0)

    # Check if user selected playback mode
    if checklist.playback_mode:
        # ========== PLAYBACK MODE (no hardware needed) ==========
        # Loop to allow user to change tests
        while True:
            log.info(f"Starting playback mode with test: {checklist.selected_test}")

            # Create playback console (no bus, no autopoller needed)
            window = MainWindow(
                loghandler=consolehandler,
                autopoller=None,
                playback_mode=True,
                test_name=checklist.selected_test
            )

            # Load test metadata and populate timeline
            metadata_path = os.path.join("testhistory", checklist.selected_test, "metadata.json")
            if os.path.exists(metadata_path):
                try:
                    with open(metadata_path, 'r') as f:
                        metadata = json.load(f)

                    # Set timeline range (support both new and old format)
                    if "start_time" in metadata and "end_time" in metadata:
                        window.timeline.min_time = metadata["start_time"]
                        window.timeline.set_total_duration(metadata["end_time"])
                        log.info(f"Test range: T{metadata['start_time']:+.1f}s to T+{metadata['end_time']:.1f}s")
                    elif "duration" in metadata:
                        # Old format compatibility
                        window.timeline.set_total_duration(metadata["duration"])
                        log.info(f"Test duration: {metadata['duration']}s")

                    # Add events to timeline
                    if "events" in metadata:
                        for event in metadata["events"]:
                            window.timeline.add_event(event["time"], event["label"])
                        log.info(f"Loaded {len(metadata['events'])} timeline events")

                    # Start at T+0 by default
                    window.timeline.set_current_time(0.0)
                    window.playback_time = 0.0

                except Exception as e:
                    log.error(f"Failed to load test metadata: {e}")
            else:
                log.warning(f"No metadata file found at {metadata_path}")

            # TODO: Load device data from saved test
            # TODO: Implement playback controls

            window.show()
            app.exec_()

            # Check if user wants to change test
            if window.change_test_requested:
                log.info("User requested to change test - showing test selection")
                # Create new checklist window and go directly to playback selection
                checklist = ChecklistWindow(settings.sender)
                checklist.show_playback_selection()
                if checklist.exec_() != QMessageBox.Accepted or not checklist.playback_mode:
                    log.info("User cancelled test selection")
                    sys.exit(0)
                # Loop continues with new selected_test
            else:
                # User closed window normally, exit
                log.info("Playback window closed")
                sys.exit(0)

    else:
        # ========== LIVE MODE (requires hardware) ==========
        log.info("Starting live mode")

        # Set up all the things
        try:
            bus = Bus(settings.sender, settings.bitrate, packetprinting=False, packetlogging=False)
            log.info("CAN bus initialized successfully")
        except Exception as e:
            log.error(f"Failed to initialize CAN bus: {e}")
            QMessageBox.critical(
                None,
                "Bus Initialization Error",
                f"Failed to initialize CAN bus:\n{str(e)}\n\n"
                f"Please check:\n"
                f"1. Device is plugged in\n"
                f"2. Device is forwarded to WSL (run 'make wsl-usb' if needed)\n"
                f"3. No other program is using the port\n\n"
                f"Then run 'make run' again."
            )
            sys.exit(1)

        with bus:
            with AutoPoller(bus=bus, interval=0.5, autostart=False) as ap:
                window = MainWindow(loghandler=consolehandler, autopoller=ap, playback_mode=False)

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