# gui/scada_webpage.py

import logging

from PyQt5.QtWebEngineWidgets import QWebEnginePage

logger = logging.getLogger(__name__)


class ScadaWebPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        logger.info(
            "[SCADA JS] %s (line %s, source=%s)",
            message,
            line_number,
            source_id,
        )
        super().javaScriptConsoleMessage(level, message, line_number, source_id)