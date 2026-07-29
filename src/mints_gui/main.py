import sys

from PySide6 import QtCore
from pyqtgraph.console import ConsoleWidget
from mints_gui.ui.main_window import MainWindow
from mints_gui.ui.widgets.logger import setup_logger
import pyqtgraph as pg

import logging

log = logging.getLogger(__name__)

pg.setConfigOption("antialias", True)


def main():
    app = pg.mkQApp("MinTS")
    log_widget = setup_logger()
    console_widget = ConsoleWidget(namespace={"app": app})
    window = MainWindow(log_widget, console_widget)
    window.show()
    timer = QtCore.QTimer()
    timer.timeout.connect(window.update_graph)
    timer.start(100)

    log.info("Welcome to MinTS!")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
