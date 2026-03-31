from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget, QMessageBox

from gui.mintsscriptapi import MintsScriptAPI
from gui.view_script import ScriptView


class _DummyTopLevel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.started: list[dict] = []
        self.stopped: list[str] = []

    def start_backend_script(self, **payload):
        self.started.append(dict(payload))

    def stop_backend_script(self, *, reason: str = "operator_stop"):
        self.stopped.append(reason)


class ScriptViewBackendRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_run_prefers_backend_owned_script_runtime(self) -> None:
        top = _DummyTopLevel()
        layout = QVBoxLayout(top)
        view = ScriptView(MintsScriptAPI())
        layout.addWidget(view)

        view.scripteditor.setPlainText('print("hello")')
        view._run()

        self.assertEqual(len(top.started), 1)
        self.assertEqual(top.started[0]["inline_python"], 'print("hello")')
        self.assertEqual(view.runbutton.text(), view.STOP_BUTTON_TEXT)
        self.assertTrue(view.running.is_set())

        view.stop()
        self.assertEqual(top.stopped, ["operator_stop"])

    def test_script_status_resets_button_state(self) -> None:
        top = _DummyTopLevel()
        layout = QVBoxLayout(top)
        view = ScriptView(MintsScriptAPI())
        layout.addWidget(view)

        view.scripteditor.setPlainText('print("hello")')
        view._run()
        view.handle_script_status({"status": "stopped"})

        self.assertFalse(view.running.is_set())
        self.assertEqual(view.runbutton.text(), view.START_BUTTON_TEXT)

    def test_without_backend_control_script_start_is_rejected(self) -> None:
        orphan_parent = QWidget()
        layout = QVBoxLayout(orphan_parent)
        view = ScriptView(MintsScriptAPI())
        layout.addWidget(view)
        view.scripteditor.setPlainText('print("local")')

        with mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok) as warning:
            view._run()

        warning.assert_called_once()
        self.assertFalse(view.running.is_set())
        self.assertEqual(view._active_runtime_owner, "idle")

    def test_idle_backend_snapshots_do_not_repeat_done_log(self) -> None:
        top = _DummyTopLevel()
        layout = QVBoxLayout(top)
        view = ScriptView(MintsScriptAPI())
        layout.addWidget(view)

        view.scripteditor.setPlainText('print("hello")')
        view._run()

        with mock.patch.object(view.log, "info") as info:
            view.handle_script_status({"status": "stopped"})
            info.assert_called_once_with("Script done running")
            info.reset_mock()

            for _ in range(3):
                view.apply_backend_state_snapshot({"script_runtime": {"is_running": False}})
                view.handle_script_status({"status": "idle"})

            info.assert_not_called()


if __name__ == "__main__":
    unittest.main()
