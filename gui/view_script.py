from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Mapping

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui import MintsScriptAPI
from scripts.script_runtime.script_contract import DEFAULT_SCRIPT_FILENAME
from scripts.script_runtime.script_protocol import (
    SCRIPT_HOST_MESSAGE_ABORT_REQUEST,
    SCRIPT_HOST_MESSAGE_COMMAND_REQUEST,
    SCRIPT_HOST_MESSAGE_SCRIPT_EXIT,
    SCRIPT_HOST_MESSAGE_SCRIPT_OUTPUT,
)
from scripts.script_runtime.script_proxy import ScriptHostProxy


class ScriptView(QWidget):
    START_BUTTON_TEXT = "Run Script"
    STOP_BUTTON_TEXT = "Stop Script"
    STOPPING_BUTTON_TEXT = "Stopping script ..."

    doneSignal = pyqtSignal()
    stoppedSignal = pyqtSignal()

    def __init__(self, mintsapi: MintsScriptAPI):
        super().__init__()
        self.log = logging.getLogger("script")
        self.running = threading.Event()
        self.mints = mintsapi
        self.runner = None
        self._active_runtime_owner = "idle"
        self._local_host_proxy: ScriptHostProxy | None = None
        self._local_host_thread: threading.Thread | None = None
        self._project_root = Path(__file__).resolve().parent.parent

        self.doneSignal.connect(self._done)
        self.stoppedSignal.connect(self._setStoppingText)

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.layout.setAlignment(Qt.AlignTop)

        self.controlLayout = QHBoxLayout()
        self.layout.addLayout(self.controlLayout)

        self.scripteditor = QPlainTextEdit()
        self.layout.addWidget(self.scripteditor)

        self.runbutton = QPushButton(self.START_BUTTON_TEXT)
        self.runbutton.clicked.connect(self._run)
        self.controlLayout.addWidget(self.runbutton)

        self.controlLayout.addStretch()

        self.openbutton = QPushButton("Open")
        self.openbutton.clicked.connect(self._load)
        self.controlLayout.addWidget(self.openbutton)

        self.savebutton = QPushButton("Save")
        self.savebutton.clicked.connect(self._save)
        self.controlLayout.addWidget(self.savebutton)

        self.lockcheck = QCheckBox("Lock editor")
        self.lockcheck.toggled.connect(self._updateLock)
        self.lockcheck.setChecked(True)
        self.controlLayout.addWidget(self.lockcheck)

        self.filename = DEFAULT_SCRIPT_FILENAME
        self._load(self.filename)

    def _load(self, filename: str | None = None):
        if filename is None:
            self.log.error("Can't try to select file yet")
            return

        self.filename = filename
        self.scripteditor.clear()

        if os.path.isfile(self.filename):
            with open(self.filename, encoding="utf-8") as f:
                for line in f:
                    self.scripteditor.insertPlainText(line)
            self.log.info("Loaded file %s", self.filename)
        else:
            self.log.error("Can not open file %s since it doesn't exist", self.filename)

    def _save(self):
        self.log.info("Saving now")
        os.makedirs(os.path.dirname(self.filename) or ".", exist_ok=True)
        with open(self.filename, "w", encoding="utf-8") as f:
            f.write(self.scripteditor.toPlainText())
        msg = f"Saved file {self.filename}"
        self.log.info(msg)
        QMessageBox.information(self.parent(), "File saved", msg)

    def _updateLock(self):
        self.log.info("Checkbox state changed")
        if self.lockcheck.isChecked():
            self._lock()
            self.log.info("Script editor locked")
            return

        ynb = QMessageBox(self.parent())
        yes = QMessageBox.StandardButton.Yes
        if (
            ynb.question(
                self.parent(),
                "Unlock Verification",
                "Do you want to unlock the editor?",
                yes | QMessageBox.StandardButton.No,
            )
            == yes
        ):
            self.log.info("Script editor unlocked")
            if not self.running.is_set():
                self._unlock()
        else:
            self.lockcheck.setChecked(True)
            self._lock()

    def _lock(self):
        self.openbutton.setEnabled(False)
        self.savebutton.setEnabled(False)
        self.scripteditor.setReadOnly(True)

    def _unlock(self, force: bool = False):
        if not self.lockcheck.checkState() == Qt.CheckState.Checked or force:
            self.openbutton.setEnabled(True)
            self.savebutton.setEnabled(True)
            self.scripteditor.setReadOnly(False)
            self.lockcheck.blockSignals(True)
            self.lockcheck.setChecked(False)
            self.lockcheck.blockSignals(False)
            self.lockcheck.setEnabled(True)
            self.lockcheck.setTristate(False)

    def _setStoppingText(self):
        self.runbutton.setText(self.STOPPING_BUTTON_TEXT)

    def _done(self):
        self.runner = None
        self._active_runtime_owner = "idle"
        self.running.clear()
        self.runbutton.setText(self.START_BUTTON_TEXT)
        self._unlock()
        self.log.info("Script done running")

    def _backend_window(self):
        window = self.window()
        if window is self:
            return None
        return window

    def _backend_script_control_available(self) -> bool:
        window = self._backend_window()
        return bool(
            window is not None
            and callable(getattr(window, "start_backend_script", None))
            and callable(getattr(window, "stop_backend_script", None))
        )

    def _script_name_for_backend(self) -> str:
        base = os.path.basename(self.filename or "")
        return base or "script.py"

    def _mark_running(self, *, runtime_owner: str) -> None:
        self.running.set()
        self._active_runtime_owner = runtime_owner
        self._lock()
        self.runbutton.setText(self.STOP_BUTTON_TEXT)
        self.lockcheck.setTristate(True)
        self.lockcheck.setEnabled(False)
        if not self.lockcheck.isChecked():
            self.lockcheck.setCheckState(Qt.CheckState.PartiallyChecked)

    def _run(self):
        if self.running.is_set():
            self.stop()
            return

        script = self.scripteditor.toPlainText()
        if not isinstance(script, str) or not script.strip():
            QMessageBox.warning(self.parent(), "No script", "There is no script text to run.")
            return

        if self._backend_script_control_available():
            self._run_via_backend(script)
            return

        self._run_via_local_subprocess(script)

    def _run_via_backend(self, script_text: str) -> None:
        window = self._backend_window()
        if window is None:
            raise RuntimeError("Backend script control window is unavailable")

        self.log.info("Starting script through backend-owned subprocess runtime")
        try:
            window.start_backend_script(
                name=self._script_name_for_backend(),
                inline_python=script_text,
                cwd=os.getcwd(),
            )
        except Exception as exc:
            self.log.exception("Failed to request backend script start")
            QMessageBox.warning(
                self.parent(),
                "Backend Error",
                f"Failed to start backend-owned script.\n\nError: {exc}",
            )
            return

        self._mark_running(runtime_owner="backend")

    def _run_via_local_subprocess(self, script_text: str) -> None:
        self.log.warning(
            "Backend script control is unavailable; using subprocess host directly instead"
        )
        proxy = ScriptHostProxy(project_root=self._project_root)
        try:
            proxy.start(script_path=self.filename, cwd=str(self._project_root))
            proxy.execute_legacy_script(script_text=script_text, device_ids=[])
        except Exception as exc:
            try:
                proxy.terminate()
            except Exception:
                pass
            self.log.exception("Failed to start local subprocess script host")
            QMessageBox.warning(
                self.parent(),
                "Script Runtime Error",
                f"Failed to start subprocess script host.\n\nError: {exc}",
            )
            return

        self._local_host_proxy = proxy
        self._mark_running(runtime_owner="local_subprocess")
        self._local_host_thread = threading.Thread(
            target=self._watch_local_host,
            name="gui-script-local-host-watcher",
            daemon=True,
        )
        self._local_host_thread.start()

    def _watch_local_host(self) -> None:
        proxy = self._local_host_proxy
        if proxy is None:
            return

        try:
            while True:
                try:
                    message = proxy.read_next_message(timeout_s=0.2)
                except TimeoutError:
                    if not proxy.is_running:
                        break
                    continue

                message_type = message.get("type")
                payload = message.get("payload")
                if not isinstance(payload, Mapping):
                    payload = {}

                if message_type == SCRIPT_HOST_MESSAGE_SCRIPT_OUTPUT:
                    text = payload.get("text")
                    if isinstance(text, str) and text:
                        self.log.info("[local script] %s", text)
                    continue

                if message_type == SCRIPT_HOST_MESSAGE_COMMAND_REQUEST:
                    self.log.warning(
                        "Ignoring local subprocess command request because backend control is unavailable: %s",
                        dict(payload),
                    )
                    continue

                if message_type == SCRIPT_HOST_MESSAGE_ABORT_REQUEST:
                    self.log.warning(
                        "Ignoring local subprocess abort request because backend control is unavailable: %s",
                        dict(payload),
                    )
                    continue

                if message_type == SCRIPT_HOST_MESSAGE_SCRIPT_EXIT:
                    break
        finally:
            try:
                if proxy.is_running:
                    proxy.shutdown(timeout_s=1.0)
                else:
                    proxy.close()
            except Exception:
                try:
                    proxy.terminate()
                except Exception:
                    pass
            self.doneSignal.emit()

    def stop(self):
        if not self.running.is_set():
            return

        if self._active_runtime_owner == "backend" and self._backend_script_control_available():
            window = self._backend_window()
            try:
                window.stop_backend_script(reason="operator_stop")
            except Exception as exc:
                self.log.exception("Failed to request backend script stop")
                QMessageBox.warning(
                    self.parent(),
                    "Backend Error",
                    f"Failed to stop backend-owned script.\n\nError: {exc}",
                )
                return
            self.stoppedSignal.emit()
            return

        if self._active_runtime_owner == "local_subprocess":
            self._stop_local_subprocess()
            return

    def _stop_local_subprocess(self) -> None:
        proxy = self._local_host_proxy
        if proxy is None:
            return
        self.stoppedSignal.emit()
        try:
            proxy.shutdown(timeout_s=1.0)
        except Exception:
            try:
                proxy.terminate()
            except Exception:
                pass
        self.doneSignal.emit()

    def scriptPrint(self, message: Any):
        self.log.info("%s", message)

    def handle_script_status(self, payload: dict[str, object]) -> None:
        if not isinstance(payload, dict):
            return
        status = str(payload.get("status") or "").strip().lower()
        if status in {"started", "running", "hold_requested", "held", "continued"}:
            if not self.running.is_set():
                self._mark_running(runtime_owner="backend")
            return
        if status in {"stopped", "finished", "completed", "exited", "idle", "not_running"}:
            self._done()

    def apply_backend_state_snapshot(self, snapshot: dict) -> None:
        if not isinstance(snapshot, dict):
            return

        section = None
        for key in ("script", "script_runtime", "script_runner"):
            candidate = snapshot.get(key)
            if isinstance(candidate, dict):
                section = candidate
                break

        if section is None:
            return

        if isinstance(section.get("is_running"), bool):
            if section.get("is_running"):
                self._mark_running(runtime_owner="backend")
            else:
                self._done()
            return

        status = section.get("status")
        if isinstance(status, str):
            self.handle_script_status({"status": status})
