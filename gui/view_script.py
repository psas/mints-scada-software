from __future__ import annotations

import logging
import os
import threading
from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui import MintsScriptAPI


class ScriptView(QWidget):
    START_BUTTON_TEXT = "Run"
    STOP_BUTTON_TEXT = "Stop"
    STOPPING_BUTTON_TEXT = "Stopping..."
    NO_SCRIPT_TEXT = "No script selected"

    doneSignal = pyqtSignal()
    stoppedSignal = pyqtSignal()

    def __init__(self, mintsapi: MintsScriptAPI):
        super().__init__()

        self.log = logging.getLogger("script")
        self.running = threading.Event()
        self.mints = mintsapi
        self.runner = None
        self._active_runtime_owner = "idle"
        self._pending_exit_info: dict | None = None
        self._seen_output_count: int = 0
        self.filename = ""

        self.doneSignal.connect(self._done)
        self.stoppedSignal.connect(self._setStoppingText)

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.layout.setAlignment(Qt.AlignTop)

        self.headerLayout = QHBoxLayout()
        self.layout.addLayout(self.headerLayout)

        self.titleLabel = QLabel("Script Control")
        self.titleLabel.setStyleSheet("font-weight: 600;")
        self.headerLayout.addWidget(self.titleLabel)

        self.headerLayout.addStretch()

        self.openbutton = QPushButton("Load")
        self.openbutton.clicked.connect(self._choose_script)
        self.headerLayout.addWidget(self.openbutton)

        self.runbutton = QPushButton(self.START_BUTTON_TEXT)
        self.runbutton.clicked.connect(self._run)
        self.headerLayout.addWidget(self.runbutton)

        self.selectedTitleLabel = QLabel("Selected script")
        self.layout.addWidget(self.selectedTitleLabel)

        self.selectedScriptLabel = QLabel(self.NO_SCRIPT_TEXT)
        self.selectedScriptLabel.setWordWrap(True)
        self.selectedScriptLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.selectedScriptLabel.setStyleSheet("font-weight: 600;")
        self.layout.addWidget(self.selectedScriptLabel)

        self._refresh_ui()

    def _dialog_start_dir(self) -> str:
        if self.filename and os.path.exists(self.filename):
            return os.path.dirname(self.filename) or os.getcwd()
        return os.getcwd()

    def _refresh_ui(self) -> None:
        has_script = bool(self.filename and os.path.isfile(self.filename))
        is_running = self.running.is_set()

        if has_script:
            self.selectedScriptLabel.setText(os.path.basename(self.filename))
            self.selectedScriptLabel.setToolTip(self.filename)
        else:
            self.selectedScriptLabel.setText(self.NO_SCRIPT_TEXT)
            self.selectedScriptLabel.setToolTip("")

        self.openbutton.setEnabled(not is_running)
        self.runbutton.setEnabled(is_running or has_script)
        self.runbutton.setText(self.STOP_BUTTON_TEXT if is_running else self.START_BUTTON_TEXT)

    def _choose_script(self, checked: bool = False) -> None:
        del checked
        self._load()

    def _load(self, filename: str | None = None) -> None:
        if self.running.is_set():
            self.log.warning("Ignoring load request while script is running")
            return

        if isinstance(filename, bool):
            filename = None

        if filename is None:
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Select script",
                self._dialog_start_dir(),
                "Python Scripts (*.py);;All Files (*)",
            )
            if not selected:
                return
            filename = selected

        candidate = os.path.abspath(filename)
        if not os.path.isfile(candidate):
            self.log.error("Cannot open file %s since it doesn't exist", candidate)
            QMessageBox.warning(
                self,
                "Script Not Found",
                f"Cannot open script file:\n\n{candidate}",
            )
            return

        self.filename = candidate
        self.log.info("Selected script %s", self.filename)
        self._refresh_ui()

    def _read_selected_script(self) -> str | None:
        if not self.filename:
            QMessageBox.warning(self, "No script selected", "Please load a script first.")
            return None

        if not os.path.isfile(self.filename):
            QMessageBox.warning(
                self,
                "Script Not Found",
                f"The selected script no longer exists:\n\n{self.filename}",
            )
            self._refresh_ui()
            return None

        try:
            with open(self.filename, encoding="utf-8") as f:
                return f.read()
        except OSError as exc:
            self.log.exception("Failed to read selected script %s", self.filename)
            QMessageBox.warning(
                self,
                "Read Error",
                f"Failed to read script file.\n\nError: {exc}",
            )
            return None

    def _setStoppingText(self) -> None:
        self.runbutton.setText(self.STOPPING_BUTTON_TEXT)

    def _done(self) -> None:
        was_active = self.running.is_set() or self._active_runtime_owner != "idle"
        self.runner = None
        self._active_runtime_owner = "idle"
        self.running.clear()
        self._refresh_ui()

        if was_active:
            exit_info = getattr(self, "_pending_exit_info", None) or {}
            self._pending_exit_info = None
            exit_status = exit_info.get("exit_status") or ""
            failure_message = exit_info.get("failure_message") or ""
            reason = exit_info.get("reason") or ""

            if exit_status == "completed":
                self.log.info("Script completed successfully.")
                self.filename = ""
                self._refresh_ui()
            elif exit_status == "failed":
                if failure_message:
                    self.log.error("Script failed: %s", failure_message)
                else:
                    self.log.error("Script failed (exit code %s).", exit_info.get("returncode", "unknown"))
            elif exit_status == "stopped":
                if reason == "operator_stop":
                    self.log.warning("Script stopped by operator.")
                else:
                    self.log.warning("Script stopped (reason: %s).", reason or "unknown")
            else:
                self.log.warning("Script exited (status=%s, reason=%s).", exit_status or "unknown", reason or "unknown")

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
        is_new_run = not self.running.is_set()
        self.running.set()
        self._active_runtime_owner = runtime_owner
        if is_new_run:
            self._pending_exit_info = None
            self._seen_output_count = 0
        self._refresh_ui()

    def _run(self) -> None:
        if self.running.is_set():
            self.stop()
            return

        script = self._read_selected_script()
        if not isinstance(script, str) or not script.strip():
            QMessageBox.warning(self, "Empty script", "The selected script file is empty.")
            return

        if not self._backend_script_control_available():
            self.log.error("Backend script control is unavailable; refusing to start script")
            QMessageBox.warning(
                self,
                "Backend Unavailable",
                (
                    "Scripts require backend control availability.\n\n"
                    "This script was not started because backend control is unavailable."
                ),
            )
            return

        self._run_via_backend(script)

    def _run_via_backend(self, script_text: str) -> None:
        window = self._backend_window()
        if window is None:
            raise RuntimeError("Backend script control window is unavailable")

        script_cwd = os.path.dirname(self.filename) or os.getcwd()

        self.log.info(
            "Starting selected script through backend-owned subprocess runtime: %s",
            self.filename or "<inline>",
        )

        try:
            window.start_backend_script(
                name=self._script_name_for_backend(),
                inline_python=script_text,
                cwd=script_cwd,
            )
        except Exception as exc:
            self.log.exception("Failed to request backend script start")
            QMessageBox.warning(
                self,
                "Backend Error",
                f"Failed to start backend-owned script.\n\nError: {exc}",
            )
            return

        self._mark_running(runtime_owner="backend")

    def stop(self) -> None:
        if not self.running.is_set():
            return

        if self._active_runtime_owner != "backend":
            self.log.error(
                "ScriptView is in unexpected runtime owner %r; refusing to stop locally",
                self._active_runtime_owner,
            )
            QMessageBox.warning(
                self,
                "Script Runtime Error",
                "Unexpected script runtime owner. The script was not stopped locally.",
            )
            return

        if not self._backend_script_control_available():
            self.log.error("Backend script control became unavailable while script was running")
            QMessageBox.warning(
                self,
                "Backend Unavailable",
                (
                    "Backend control is unavailable, so this window cannot stop the "
                    "running script directly."
                ),
            )
            return

        window = self._backend_window()
        try:
            window.stop_backend_script(reason="operator_stop")
        except Exception as exc:
            self.log.exception("Failed to request backend script stop")
            QMessageBox.warning(
                self,
                "Backend Error",
                f"Failed to stop backend-owned script.\n\nError: {exc}",
            )
            return

        self.stoppedSignal.emit()

    def scriptPrint(self, message: Any) -> None:
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
            if self.running.is_set() or self._active_runtime_owner != "idle":
                exit_info = {
                    "exit_status": payload.get("exit_status") or ("stopped" if status == "stopped" else None),
                    "failure_message": payload.get("failure_message"),
                    "reason": payload.get("reason"),
                    "returncode": payload.get("returncode"),
                }
                self._pending_exit_info = exit_info
                self.doneSignal.emit()

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

        output_lines = section.get("output_lines")
        if isinstance(output_lines, list):
            already_seen = getattr(self, "_seen_output_count", 0)
            for line in output_lines[already_seen:]:
                if isinstance(line, str) and line.strip():
                    self.log.info("[script] %s", line)
            self._seen_output_count = len(output_lines)

        if isinstance(section.get("is_running"), bool):
            if section.get("is_running"):
                self._mark_running(runtime_owner="backend")
            else:
                if self.running.is_set() or self._active_runtime_owner != "idle":
                    self._pending_exit_info = {
                        "exit_status": section.get("last_exit_status"),
                        "failure_message": section.get("last_failure_message"),
                        "reason": section.get("last_stop_reason"),
                        "returncode": section.get("last_exit_code"),
                    }
                    self.doneSignal.emit()
            return

        status = section.get("status")
        if isinstance(status, str):
            self.handle_script_status({"status": status})