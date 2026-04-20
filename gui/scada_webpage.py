"""gui/scada_webpage.py

SCADA-specific web page wrapper for JavaScript console logging.
"""

import logging

from PyQt5.QtWebEngineWidgets import QWebEnginePage

logger = logging.getLogger(__name__)


class ScadaWebPage(QWebEnginePage):
    """Route SCADA webpage JavaScript console output into the Python logger."""

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        """Log a JavaScript console message emitted by the SCADA webpage.

        Args:
            level: Web engine console message level supplied by Qt.
            message: Console message text emitted by the page.
            line_number: Source line number associated with the message.
            source_id: Script source identifier reported by the web engine.

        Returns:
            None.
        """
        logger.info(
            "[SCADA JS] %s (line %s, source=%s)",
            message,
            line_number,
            source_id,
        )
        super().javaScriptConsoleMessage(level, message, line_number, source_id)
