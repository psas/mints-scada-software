# gui/finalization_guard.py

"""Finalization guard: blocks app close while archive save is in progress.

Provides a shared dialog and background auto-close timer used by both the
controller and scada windows to prevent shutdown before ``complete.json``
has been written.
"""
from __future__ import annotations

import logging
from typing import Callable

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

log = logging.getLogger(__name__)

# Dialog result codes returned via FinalizationWaitDialog.result_code
RESULT_KEEP_WAITING = 0
RESULT_COMPLETED = 1
RESULT_FORCE_CLOSE = 2


class FinalizationWaitDialog(QDialog):
    """Modal dialog shown while archive finalization is in progress.

    Polls *check_complete_fn* on a timer.  When the callable returns ``True``
    the dialog auto-accepts so the caller can proceed with shutdown.  The
    operator may also choose *Keep Waiting* (dismiss dialog, app stays open)
    or *Close Anyway* (force immediate shutdown).
    """

    def __init__(
        self,
        parent,
        check_complete_fn: Callable[[], bool],
        *,
        poll_interval_ms: int = 500,
    ) -> None:
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
        return self._result_code

    # -- internal -------------------------------------------------------------

    def _poll(self) -> None:
        try:
            if self._check_complete():
                self._poll_timer.stop()
                self._result_code = RESULT_COMPLETED
                log.info("Archive finalization confirmed while dialog was open")
                self.accept()
        except Exception:
            log.debug("Finalization poll check failed", exc_info=True)

    def _on_keep_waiting(self) -> None:
        self._poll_timer.stop()
        self._result_code = RESULT_KEEP_WAITING
        self.reject()

    def _on_force_close(self) -> None:
        self._poll_timer.stop()
        self._result_code = RESULT_FORCE_CLOSE
        self.accept()

    def closeEvent(self, event) -> None:
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
    """Start a background timer on *window* that auto-closes it when
    *check_complete_fn* returns ``True``.

    Called after the operator chooses *Keep Waiting*.  Sets a bypass flag
    so the subsequent ``closeEvent`` does not re-open the dialog.
    """
    timer_attr = "_finalization_auto_close_timer"
    existing = getattr(window, timer_attr, None)
    if isinstance(existing, QTimer) and existing.isActive():
        return  # already watching

    timer = QTimer(window)
    timer.setInterval(interval_ms)

    def _check() -> None:
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
