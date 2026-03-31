from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QPushButton, QWidget

from gui.window_host import _setup_abort_controls


class _DummyWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.btn_abort = QPushButton("Abort", self)
        self.abort_relay_available = True
        self.abort_relay_socket_path = "/tmp/test-abort-relay.sock"


class AbortButtonWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_scada_uses_standard_abort_button_instead_of_overlay(self) -> None:
        actual_window = _DummyWindow()
        facade = SimpleNamespace()

        _setup_abort_controls(
            actual_window=actual_window,
            facade=facade,
            mode="live",
            window_kind="scada",
        )

        self.assertTrue(callable(getattr(actual_window, "trigger_abort_via_relay", None)))
        self.assertEqual(
            actual_window.btn_abort.toolTip(),
            "Send abort through AbortRelay and backend command dispatch",
        )
        self.assertFalse(hasattr(actual_window, "_abort_overlay_button"))
        self.assertFalse(hasattr(actual_window, "_abort_overlay_controller"))


if __name__ == "__main__":
    unittest.main()
