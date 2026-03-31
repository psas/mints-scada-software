from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget

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


class _DummyLocalHostProxy:
    def __init__(self, *args, **kwargs) -> None:
        self.started = False
        self.executed = False
        self.closed = False

    @property
    def is_running(self) -> bool:
        return False

    def start(self, *, script_path=None, cwd=None):
        self.started = True
        return {"type": "host_ready", "payload": {"pid": 1234}}

    def execute_legacy_script(self, *, script_text: str, device_ids: list[str]):
        self.executed = True
        return {"type": "execute_started", "payload": {"ok": True}}

    def read_next_message(self, *, timeout_s: float = 0.5):
        return {"type": "script_exit", "payload": {"returncode": 0}}

    def shutdown(self, *, timeout_s: float = 1.0):
        self.closed = True
        return {"type": "shutdown_ack", "payload": {"ok": True}}

    def close(self) -> None:
        self.closed = True

    def terminate(self):
        self.closed = True


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

    def test_without_backend_control_it_still_uses_subprocess_host(self) -> None:
        host = _DummyLocalHostProxy()
        orphan_parent = QWidget()
        layout = QVBoxLayout(orphan_parent)
        view = ScriptView(MintsScriptAPI())
        layout.addWidget(view)
        view.scripteditor.setPlainText('print("local")')

        with mock.patch("gui.view_script.ScriptHostProxy", return_value=host):
            view._run()

        self.assertTrue(host.started)
        self.assertTrue(host.executed)
        self.assertIn(view._active_runtime_owner, {"local_subprocess", "idle"})


if __name__ == "__main__":
    unittest.main()
