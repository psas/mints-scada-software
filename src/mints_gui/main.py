from errno import EFTYPE
import logging
import sys
from argparse import ArgumentParser

import pyqtgraph as pg
from pyqtgraph.console import ConsoleWidget
from PySide6 import QtCore

from config import config as CFG
from mints_backend.can_bus import CanBus
from mints_backend.devices.device_manager import DeviceManager
from mints_gui.ui.main_window import MainWindow
from mints_gui.ui.widgets.logger import setup_logger

log = logging.getLogger(__name__)

pg.setConfigOption("antialias", True)

parser = ArgumentParser()
parser.add_argument(
    "--bus", "-b", help="name of the CAN interface", type=str, required=False
)


def main():
    args = parser.parse_args()
    app = pg.mkQApp("MinTS")
    log_widget = setup_logger()

    try:
        can = CanBus(args.bus)
    except OSError as e:
        log.error("Unable to connect to CAN bus -- %s", e.strerror)
        sys.exit(e.errno)

    try:
        device_manager = DeviceManager()
    except IndexError as e:
        log.error("Error parsing devices from config: %s", e)
        sys.exit(EFTYPE)

    console_widget = ConsoleWidget(
        namespace={
            "app": app,
            "config": CFG,
            "can": can,
            "devices": device_manager,
        }
    )

    window = MainWindow(log_widget, console_widget)

    timer = QtCore.QTimer()
    timer.timeout.connect(window.update_graph)
    timer.start(100)

    log.info("Welcome to MinTS!")
    can.start()
    window.show()
    exit_code = app.exec()

    can.shutdown()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
