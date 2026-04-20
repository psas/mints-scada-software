"""gui/qlogginghandler.py

Qt logging handler that buffers records until a log widget is requested.
"""

import logging
from PyQt5.QtWidgets import QPlainTextEdit


class QLoggingHandler(logging.Handler):
    """Route Python logging records into a lazily created Qt text widget.

    The handler stores incoming records in memory until the GUI asks for the
    widget. This lets application code configure logging before the Qt widget
    tree is fully constructed.
    """

    def __init__(self):
        """Initialize the handler and in-memory record cache.

        Returns:
            None.
        """
        super().__init__()
        self.__widget = None
        self.cache = []

    @property
    def widget(self):
        """Return the lazily created log display widget.

        The widget is constructed on first access, configured as a read-only
        no-wrap text area, and backfilled with any records that were emitted
        before the GUI requested the widget.

        Returns:
            The plain-text log display widget used by this handler.
        """
        if self.__widget is None:
            self.__widget = QPlainTextEdit()
            self.__widget.setReadOnly(True)
            self.__widget.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            for record in self.cache:
                msg = self.format(record)
                self.__widget.appendPlainText(msg)
        return self.__widget

    def emit(self, record):
        """Cache and display a formatted log record.

        Args:
            record: Log record to format and append.

        Returns:
            None.
        """
        msg = self.format(record)
        self.cache.append(record)
        if self.__widget is not None:
            self.__widget.appendPlainText(msg)
