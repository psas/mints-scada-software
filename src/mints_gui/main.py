import logging
import sys
from argparse import ArgumentParser

import pyqtgraph as pg
from pydantic import ValidationError
from pyqtgraph.console import ConsoleWidget

from config import config as CFG
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
        device_manager = DeviceManager(args.bus)
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
    except OSError as e:
        log.error("Unable to connect to CAN bus - %s", e.strerror)
        sys.exit(e.errno)

    console_widget = ConsoleWidget(
        namespace={
            "app": app,
            "config": CFG,
            "can": device_manager.bus,
            "devices": device_manager,
        }
    )

    window = MainWindow(log_widget, console_widget if CFG["debug"]["console"] else None, device_manager)

    log.info("Welcome to MinTS!")
    window.show()
    exit_code = app.exec()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
