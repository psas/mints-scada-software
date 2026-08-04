import logging
import sys
from argparse import ArgumentParser

from pydantic import ValidationError
import pyqtgraph as pg
from pyqtgraph.console import ConsoleWidget
from PySide6 import QtCore

from config import config as CFG
from mints_backend.can_bus import CanBus
from mints_backend.device_manager import DeviceManager
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
        device_manager = DeviceManager(can)
    except ValidationError as e:
        err_details = e.errors()
        for err in err_details:
            log.error(
                "Validation error in board config file. Field: %s. Found: '%s' - %s",
                err["loc"],
                err["input"],
                err["msg"],
            )
        sys.exit(1)
    except KeyError or ValueError as e:
        log.error("%s", e)
        sys.exit(1)

    console_widget = ConsoleWidget(
        namespace={
            "app": app,
            "config": CFG,
            "can": can,
            "devices": device_manager,
        }
    )

    window = MainWindow(log_widget, console_widget if CFG["debug"]["console"] else None)

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
