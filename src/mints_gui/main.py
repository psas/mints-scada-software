import logging
import sys
from argparse import ArgumentParser

import pyqtgraph as pg

from mints_backend.device_manager import try_setup_device_manager
from mints_gui.logging import (
    SignalHandler,
    setup_logging,
)
from mints_gui.ui.main_window import MainWindow

log = logging.getLogger(__name__)

pg.setConfigOption("antialias", True)

parser = ArgumentParser()
parser.add_argument(
    "--bus", "-b", help="name of the CAN interface", type=str, required=False
)


def main():
    args = parser.parse_args()
    app = pg.mkQApp("MinTS")
    log_signal = SignalHandler()
    setup_logging(log_signal)

    device_manager = try_setup_device_manager(args.bus)
    window = MainWindow(log_signal, device_manager)

    log.info("Welcome to MinTS!")
    window.show()

    exit_code = app.exec()
    device_manager.teardown()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
