"""gui/finalization_guard.py

Guard application shutdown while archive finalization is still running.

This module provides the shared finalization-wait dialog and the background
auto-close timer used by GUI windows that must stay open until archive
finalization has written the completion marker.

Module-level constants ``RESULT_KEEP_WAITING``, ``RESULT_COMPLETED``, and
``RESULT_FORCE_CLOSE`` are the dialog result codes returned via
``FinalizationWaitDialog.result_code``.
"""
from __future__ import annotations

import logging
from typing import Callable

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

log = logging.getLogger(__name__)

RESULT_KEEP_WAITING = 0
RESULT_COMPLETED = 1
RESULT_FORCE_CLOSE = 2


class FinalizationWaitDialog(QDialog):
    """Wait for archive finalization or let the operator override shutdown.

    The dialog polls a caller-provided completion check while the archive is
    still being finalized. It auto-accepts when finalization completes, or the
    operator can either keep the application open or force immediate shutdown.
    """

    def __init__(
        self,
        parent,
        check_complete_fn: Callable[[], bool],
        *,
        poll_interval_ms: int = 500,
    ) -> None:
        """Initialize the finalization-wait dialog.

        Args:
            parent: Parent widget that owns the dialog.
            check_complete_fn: Callable that returns True once archive
                finalization has completed.
            poll_interval_ms: Poll interval, in milliseconds, for checking
                archive completion.
        """
        super().__init__(parent)
        self.setWindowTitle("Save in Progress")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._check_complete = check_complete_fn
        self._result_code = RESULT_KEEP_WAITING

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        msg = QLabel(
            "Save in progress, please wait patiently.\n\n"
            "The software will close after all data have been saved successfully."
        )
        msg.setWordWrap(True)
        layout.addWidget(msg)

        self._status_label = QLabel("Waiting for archive finalization\u2026")
        self._status_label.setStyleSheet("color: #888; font-style: italic;")
        layout.addWidget(self._status_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_wait = QPushButton("Keep Waiting")
        btn_wait.setDefault(True)
        btn_wait.clicked.connect(self._on_keep_waiting)
        btn_layout.addWidget(btn_wait)

        btn_force = QPushButton("Close Anyway")
        btn_force.clicked.connect(self._on_force_close)
        btn_layout.addWidget(btn_force)

        layout.addLayout(btn_layout)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(poll_interval_ms)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    @property
    def result_code(self) -> int:
        """Return the dialog outcome code.

        Returns:
            One of RESULT_KEEP_WAITING, RESULT_COMPLETED, or
            RESULT_FORCE_CLOSE.
        """
        return self._result_code

    # -- internal -------------------------------------------------------------

    def _poll(self) -> None:
        """Poll for archive completion and auto-accept when it finishes.

        Returns:
            None.
        """
        try:
            if self._check_complete():
                self._poll_timer.stop()
                self._result_code = RESULT_COMPLETED
                log.info("Archive finalization confirmed while dialog was open")
                self.accept()
        except Exception:
            log.debug("Finalization poll check failed", exc_info=True)

    def _on_keep_waiting(self) -> None:
        """Dismiss the dialog and leave the application open.

        Returns:
            None.
        """
        self._poll_timer.stop()
        self._result_code = RESULT_KEEP_WAITING
        self.reject()

    def _on_force_close(self) -> None:
        """Accept the dialog and allow immediate shutdown.

        Returns:
            None.
        """
        self._poll_timer.stop()
        self._result_code = RESULT_FORCE_CLOSE
        self.accept()

    def closeEvent(self, event) -> None:
        """Treat manual dialog close actions as a keep-waiting decision.

        Args:
            event: Qt close event for the dialog.

        Returns:
            None.
        """
        # Dialog X-button or Escape treated as Keep Waiting.
        self._poll_timer.stop()
        self._result_code = RESULT_KEEP_WAITING
        event.accept()


def start_finalization_auto_close_timer(
    window,
    check_complete_fn: Callable[[], bool],
    *,
    interval_ms: int = 500,
) -> None:
    """Start a background watcher that closes a window after finalization.

    This is used after the operator chooses Keep Waiting. When the completion
    check begins returning True, the helper sets the window's
    ``_finalization_bypass`` flag and closes the window so its later
    ``closeEvent`` path does not reopen the guard dialog.

    Args:
        window: Window that should close automatically after archive
            finalization completes.
        check_complete_fn: Callable that returns True once archive
            finalization has completed.
        interval_ms: Poll interval, in milliseconds, for the background check.

    Returns:
        None.
    """
    timer_attr = "_finalization_auto_close_timer"
    existing = getattr(window, timer_attr, None)
    if isinstance(existing, QTimer) and existing.isActive():
        return  # already watching

    timer = QTimer(window)
    timer.setInterval(interval_ms)

    def _check() -> None:
        """Close the window once archive finalization completes.

        Returns:
            None.
        """
        try:
            if check_complete_fn():
                timer.stop()
                log.info("Archive finalization complete - auto-closing window")
                window._finalization_bypass = True
                window.close()
        except Exception:
            log.debug("Auto-close poll check failed", exc_info=True)

    timer.timeout.connect(_check)
    timer.start()
    setattr(window, timer_attr, timer)
    log.info("Started background finalization auto-close timer")
