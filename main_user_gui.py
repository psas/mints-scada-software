from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import settings
from typing import Any

from PyQt5.QtWidgets import QApplication, QMessageBox

from gui import ChecklistWindow, QLoggingHandler

log = logging.getLogger(__name__)


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _encode_json_arg(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _configure_logging() -> QLoggingHandler:
    formatstr = "%(asctime)s [%(name)-16.16s] [%(levelname)-5.5s] %(message)s"
    consolehandler = QLoggingHandler()
    consolehandler.setFormatter(logging.Formatter(formatstr))

    log_dir = _project_root() / "log"
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.DEBUG,
        format=formatstr,
        handlers=[
            logging.FileHandler(log_dir / "debug.log"),
            logging.StreamHandler(),
            consolehandler,
        ],
    )

    return consolehandler


def _supervisor_script() -> Path:
    script_path = _project_root() / "gui" / "supervisor.py"
    if not script_path.is_file():
        raise FileNotFoundError(f"Missing GUI supervisor script: {script_path}")
    return script_path


def _spawn_supervisor(
    *,
    mode: str,
    selected_test: str | None = None,
    start_run_payload: dict[str, Any] | None = None,
) -> int:
    script_path = _supervisor_script()
    socket_path = _project_root() / ".backend_service.sock"

    cmd = [
        sys.executable,
        str(script_path),
        "--mode",
        mode,
        "--backend-socket",
        str(socket_path),
    ]

    if selected_test:
        cmd.extend(["--selected-test", selected_test])

    encoded_payload = _encode_json_arg(start_run_payload)
    if encoded_payload:
        cmd.extend(["--start-run-payload-b64", encoded_payload])

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    process = subprocess.Popen(
        cmd,
        cwd=str(_project_root()),
        env=env,
        text=True,
        start_new_session=False,
    )
    log.info("Spawned GUI supervisor pid=%s for mode=%s", process.pid, mode)

    try:
        return process.wait()
    except KeyboardInterrupt:
        log.info("Launcher interrupted; terminating GUI supervisor pid=%s", process.pid)
        _terminate_process(process, label="gui supervisor")
        _wait_for_process_exit(process, timeout_s=2.0)
        if process.poll() is None:
            _kill_process(process, label="gui supervisor")
            _wait_for_process_exit(process, timeout_s=1.0)
        return 130


def _terminate_process(process: subprocess.Popen[str], *, label: str) -> None:
    if process.poll() is not None:
        return

    try:
        log.info("Terminating %s pid=%s", label, process.pid)
        process.terminate()
    except Exception as exc:
        log.warning("Failed to terminate %s pid=%s: %s", label, process.pid, exc)


def _kill_process(process: subprocess.Popen[str], *, label: str) -> None:
    if process.poll() is not None:
        return

    try:
        log.warning("Killing %s pid=%s", label, process.pid)
        process.kill()
    except Exception as exc:
        log.warning("Failed to kill %s pid=%s: %s", label, process.pid, exc)


def _wait_for_process_exit(process: subprocess.Popen[str], *, timeout_s: float) -> None:
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        pass



def main() -> int:
    app = QApplication(sys.argv)
    _configure_logging()
    log.debug("Starting user GUI launcher entrypoint")

    checklist = ChecklistWindow(settings.sender)
    result = checklist.exec_()
    if result != ChecklistWindow.Accepted:
        log.info("Checklist cancelled; exiting launcher")
        return 0

    if checklist.playback_mode:
        selected_test = checklist.selected_test
        if not selected_test:
            QMessageBox.critical(
                None,
                "Playback Error",
                "Playback mode was selected, but no playback run was provided.",
            )
            return 1
        log.info("Launching GUI supervisor for playback run: %s", selected_test)
        return _spawn_supervisor(mode="playback", selected_test=selected_test)

    start_run_payload = dict(checklist.live_run_metadata or {}) or None
    log.info("Launching GUI supervisor for live session with metadata: %s", start_run_payload)
    return _spawn_supervisor(mode="live", start_run_payload=start_run_payload)


if __name__ == "__main__":
    sys.exit(main())
