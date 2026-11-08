from __future__ import annotations

import logging
from logging import Handler, LogRecord, getLogger
from pathlib import Path
from typing import override

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QPlainTextEdit, QSizePolicy

from config import config as CFG

log = getLogger(__name__)

APP_LOG_LEVEL = CFG.get("logging", {}).get("level", "INFO").upper()


def setup_logging(signalhandler: SignalHandler) -> None:
    create_log_dir_and_file_if_not_exists()

    logging.basicConfig(
        level=APP_LOG_LEVEL,
        handlers=[
            make_log_file_handler(),
            make_log_stream_handler(),
            signalhandler,
        ],
    )


class SignalHandler(Handler, QObject):
    sig_output_log = Signal(str)

    def __init__(self):
        super().__init__()
        QObject.__init__(self)
        formatter = ShortFormatter()
        self.setFormatter(formatter)

    @override
    def emit(self, record: LogRecord) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        msg = self.format(record)
        self.sig_output_log.emit(msg)


class LogConsoleWidget(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setBaseSize(1, 10)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)


class ShortFormatter(logging.Formatter):
    def __init__(self):
        self.formatstr = "%(asctime)s [%(levelname)-4.4s] %(message)s"
        self.shortdatefmt = "%H:%M:%S"
        super().__init__(fmt=self.formatstr, datefmt=self.shortdatefmt)

    def format(self, record):
        record.name = record.name.split(".")[-1]
        return super().format(record)


def create_log_dir_and_file_if_not_exists() -> None:
    app_dir = Path.cwd()
    if not Path.is_dir(app_dir / "log"):
        Path.mkdir(app_dir / "log")
    log_dir = app_dir / "log"
    if not Path.exists(log_dir / "debug.log"):
        with open(Path(log_dir / "debug.log"), "a") as file:
            file.write("")


def make_log_stream_handler() -> Handler:
    streamhandler = logging.StreamHandler()
    streamhandler.setFormatter(ShortFormatter())
    return streamhandler


def make_log_file_handler() -> Handler:
    file_formatstr = "%(asctime)s [%(name)-30.30s] [%(levelname)-5.5s] %(message)s"
    file_formatter = logging.Formatter(file_formatstr)
    filehandler = logging.FileHandler("log/debug.log")
    filehandler.setFormatter(file_formatter)
    return filehandler
