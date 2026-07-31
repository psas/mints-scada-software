from logging import LogRecord, Handler, getLogger
import logging
import os
from typing import override
from PySide6.QtWidgets import QPlainTextEdit, QWidget
from PySide6.QtCore import QObject, Signal

log = getLogger(__name__)

APP_LOG_LEVEL = logging.DEBUG


class QLoggingHandler(Handler, QObject):
    appendPlainText = Signal(str)

    def __init__(self):
        super().__init__()
        QObject.__init__(self)
        self.widget = QPlainTextEdit()
        self.widget.setReadOnly(True)
        self.widget.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.appendPlainText.connect(self.widget.appendPlainText)

    @override
    def emit(self, record: LogRecord) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        msg = self.format(record)
        self.appendPlainText.emit(msg)


class ShortNameFormatter(logging.Formatter):
    def format(self, record):
        record.name = record.name.split(".")[-1]
        return super().format(record)


def setup_logger() -> QWidget:
    formatstr = "%(asctime)s [%(name)-13.13s] [%(levelname)-5.5s]  %(message)s"
    shortdatefmt = "%H:%M:%S"
    formatter = ShortNameFormatter(fmt=formatstr, datefmt=shortdatefmt)
    consolehandler = QLoggingHandler()
    consolehandler.setFormatter(formatter)
    streamhandler = logging.StreamHandler()
    streamhandler.setFormatter(formatter)
    file_formatstr = "%(asctime)s [%(name)-30.30s] [%(levelname)-5.5s]  %(message)s"
    file_formatter = logging.Formatter(file_formatstr)
    filehandler = logging.FileHandler("log/debug.log")
    filehandler.setFormatter(file_formatter)

    if not os.path.isdir("log"):
        os.mkdir("log")

    logging.basicConfig(
        level=APP_LOG_LEVEL,
        handlers=[
            filehandler,
            streamhandler,
            consolehandler,
        ],
    )

    return consolehandler.widget
