import sys

from PySide6 import QtCore
from pyqtgraph.console import ConsoleWidget
from mints_backend.api import BackendApi
from mints_gui.ui.main_window import MainWindow
from mints_gui.ui.widgets.logger import setup_logger
import pyqtgraph as pg
from argparse import ArgumentParser

import logging

log = logging.getLogger(__name__)

pg.setConfigOption("antialias", True)

parser = ArgumentParser()
parser.add_argument('--bus', '-b', help='name of the CAN interface', type=str)

def main():
    args = parser.parse_args()
    app = pg.mkQApp("MinTS")

    log_widget = setup_logger()
    console_widget = ConsoleWidget(namespace={"app": app})

    window = MainWindow(log_widget, console_widget)

    api = BackendApi(args.bus)
    api.start()

    timer = QtCore.QTimer()
    timer.timeout.connect(window.update_graph)
    timer.start(100)

    log.info("Welcome to MinTS!")
    window.show()
    exit = app.exec()
    api.shutdown()
    sys.exit(exit)


if __name__ == "__main__":
    main()
