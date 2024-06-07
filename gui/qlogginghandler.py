import logging
from PyQt5.QtWidgets import QPlainTextEdit

class QLoggingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.__widget = None
        self.cache = []

    @property
    def widget(self):
        ''' Generates the widget if DNE, and returns it. Needed since you may want to create the logger before starting GUI construction. '''
        if self.__widget is None:
            self.__widget = QPlainTextEdit()
            self.__widget.setReadOnly(True)
            self.__widget.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            for record in self.cache:
                msg = self.format(record)
                self.__widget.appendPlainText(msg)
        return self.__widget

    def emit(self, record):
        msg = self.format(record)
        self.cache.append(record)
        if self.__widget is not None:
            self.__widget.appendPlainText(msg)