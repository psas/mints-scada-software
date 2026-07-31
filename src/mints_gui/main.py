import logging
import sys
from argparse import ArgumentParser

import pyqtgraph as pg
from box import Box
from pyqtgraph.console import ConsoleWidget
from PySide6 import QtCore

from mints_backend.api import BackendApi
from mints_gui.ui.main_window import MainWindow
from mints_gui.ui.widgets.logger import setup_logger

log = logging.getLogger(__name__)

pg.setConfigOption("antialias", True)

SETTINGS = Box.from_toml(filename="settings.toml")

parser = ArgumentParser()
parser.add_argument(
    "--bus", "-b", help="name of the CAN interface", type=str, required=False
)


def main():
    args = parser.parse_args()
    app = pg.mkQApp("MinTS")
    log_widget = setup_logger()
    api = BackendApi(args.bus)

    console_widget = ConsoleWidget(
        namespace={"app": app, "settings": SETTINGS, "api": api}
    )

    window = MainWindow(log_widget, console_widget)

    timer = QtCore.QTimer()
    timer.timeout.connect(window.update_graph)
    timer.start(100)

    log.info("Welcome to MinTS!")
    api.start()
    window.show()
    exit_code = app.exec()

    api.shutdown()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
