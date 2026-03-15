from __future__ import annotations

import base64
import json
import logging
import os
import signal
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


def _window_host_script() -> Path:
    script_path = _project_root() / "gui" / "window_host.py"
    if not script_path.is_file():
        raise FileNotFoundError(f"Missing window host script: {script_path}")
    return script_path


def _spawn_window_process(
    *,
    mode: str,
    window_kind: str,
    selected_test: str | None = None,
    start_run_payload: dict[str, Any] | None = None,
) -> subprocess.Popen[str]:
    script_path = _window_host_script()
    socket_path = _project_root() / ".backend_service.sock"

    cmd = [
        sys.executable,
        str(script_path),
        "--mode",
        mode,
        "--window-kind",
        window_kind,
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
    log.info(
        "Spawned %s %s window host pid=%s",
        mode,
        window_kind,
        process.pid,
    )
    return process


def _spawn_live_windows(*, start_run_payload: dict[str, Any] | None) -> int:
    processes: list[subprocess.Popen[str]] = []
    try:
        controller_process = _spawn_window_process(
            mode="live",
            window_kind="controller",
            start_run_payload=start_run_payload,
        )
        processes.append(controller_process)

        scada_process = _spawn_window_process(
            mode="live",
            window_kind="scada",
            start_run_payload=None,
        )
        processes.append(scada_process)

        return _run_window_session(
            mode="live",
            controller_process=controller_process,
            scada_process=scada_process,
        )
    except Exception as exc:
        for process in processes:
            try:
                process.terminate()
            except Exception:
                pass
        QMessageBox.critical(
            None,
            "GUI Launch Error",
            "Failed to launch split live GUI windows.\n\n"
            f"Error: {exc}",
        )
        return 1


def _spawn_playback_windows(*, selected_test: str) -> int:
    processes: list[subprocess.Popen[str]] = []
    try:
        controller_process = _spawn_window_process(
            mode="playback",
            window_kind="controller",
            selected_test=selected_test,
        )
        processes.append(controller_process)

        scada_process = _spawn_window_process(
            mode="playback",
            window_kind="scada",
            selected_test=selected_test,
        )
        processes.append(scada_process)

        return _run_window_session(
            mode="playback",
            controller_process=controller_process,
            scada_process=scada_process,
        )
    except Exception as exc:
        for process in processes:
            try:
                process.terminate()
            except Exception:
                pass
        QMessageBox.critical(
            None,
            "Playback Launch Error",
            "Failed to launch split playback GUI windows.\n\n"
            f"Error: {exc}",
        )
        return 1


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


def _run_window_session(
    *,
    mode: str,
    controller_process: subprocess.Popen[str],
    scada_process: subprocess.Popen[str],
) -> int:
    child_map = {
        "controller": controller_process,
        "scada": scada_process,
    }

    log.info(
        "Entering split-window session coordinator for mode=%s (controller pid=%s, scada pid=%s)",
        mode,
        controller_process.pid,
        scada_process.pid,
    )

    try:
        while True:
            exited_name = None
            exited_code = None

            for name, process in child_map.items():
                return_code = process.poll()
                if return_code is not None:
                    exited_name = name
                    exited_code = return_code
                    break

            if exited_name is None:
                time.sleep(0.2)
                continue

            log.info(
                "%s window process exited with code=%s; shutting down remaining GUI windows for this session",
                exited_name,
                exited_code,
            )

            for name, process in child_map.items():
                if name == exited_name:
                    continue
                _terminate_process(process, label=f"{name} window")
                _wait_for_process_exit(process, timeout_s=2.0)
                if process.poll() is None:
                    _kill_process(process, label=f"{name} window")
                    _wait_for_process_exit(process, timeout_s=1.0)

            return int(exited_code or 0)

    except KeyboardInterrupt:
        log.info("Launcher interrupted; terminating child GUI windows")
        for name, process in child_map.items():
            _terminate_process(process, label=f"{name} window")
        for process in child_map.values():
            _wait_for_process_exit(process, timeout_s=2.0)
        for name, process in child_map.items():
            if process.poll() is None:
                _kill_process(process, label=f"{name} window")
        return 130


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
        log.info("Launching split playback windows for run: %s", selected_test)
        return _spawn_playback_windows(selected_test=selected_test)

    start_run_payload = dict(checklist.live_run_metadata or {}) or None
    log.info("Launching split live windows with metadata: %s", start_run_payload)
    return _spawn_live_windows(start_run_payload=start_run_payload)


if __name__ == "__main__":
    sys.exit(main())
