from logging import LogRecord, Handler, getLogger
import logging
import os
from typing import override
from PySide6.QtWidgets import QPlainTextEdit, QWidget

log = getLogger(__name__)

APP_LOG_LEVEL = logging.DEBUG

class QLoggingHandler(Handler):
    def __init__(self):
        super().__init__()
        self.__widget = None
        self.buf: list[LogRecord] = []

    @property
    def widget(self) -> QPlainTextEdit:
        if self.__widget is not None:
            return self.__widget

        self.__widget = QPlainTextEdit()
        self.__widget.setReadOnly(True)
        self.__widget.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        for record in self.buf:
            msg = self.format(record)
            self.__widget.appendPlainText(msg)

        return self.__widget

    @override
    def emit(self, record: LogRecord) -> None:
        if self.__widget is None:
            raise ValueError("Logger widget not initialized")

        msg = self.format(record)
        self.buf.append(record)
        self.__widget.appendPlainText(msg)


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
