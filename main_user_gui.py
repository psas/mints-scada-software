from __future__ import annotations

import base64
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
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

def _abort_relay_script() -> Path:
    script_path = _project_root() / "gui" / "abort_relay.py"
    if not script_path.is_file():
        raise FileNotFoundError(f"Missing AbortRelay script: {script_path}")
    return script_path


def _ping_abort_relay(socket_path: Path, *, timeout_s: float = 0.75) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout_s)
            sock.connect(str(socket_path))
            wire = json.dumps({"type": "ping", "payload": {}}, ensure_ascii=False, sort_keys=False) + "\n"
            sock.sendall(wire.encode("utf-8"))
            buffer = ""
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    decoded = json.loads(line)
                    if isinstance(decoded, dict) and decoded.get("type") == "pong":
                        return True
    except Exception:
        return False
    return False


def _spawn_abort_relay() -> tuple[subprocess.Popen[str], Path]:
    script_path = _abort_relay_script()
    backend_socket = _project_root() / ".backend_service.sock"

    socket_dir = Path(tempfile.gettempdir()) / "mints_scada_abort"
    socket_dir.mkdir(parents=True, exist_ok=True)
    relay_socket = socket_dir / f"gui_abort_relay_{os.getpid()}.sock"
    if relay_socket.exists():
        relay_socket.unlink()

    cmd = [
        sys.executable,
        str(script_path),
        "--backend-socket",
        str(backend_socket),
        "--relay-socket",
        str(relay_socket),
    ]

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    process = subprocess.Popen(
        cmd,
        cwd=str(_project_root()),
        env=env,
        text=True,
        start_new_session=False,
    )
    log.info("Spawned AbortRelay pid=%s socket=%s", process.pid, relay_socket)

    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"AbortRelay exited early with code {process.poll()}")
        if relay_socket.exists() and _ping_abort_relay(relay_socket):
            return process, relay_socket
        time.sleep(0.1)

    _terminate_process(process, label="abort relay")
    _wait_for_process_exit(process, timeout_s=1.0)
    if process.poll() is None:
        _kill_process(process, label="abort relay")
        _wait_for_process_exit(process, timeout_s=1.0)
    raise RuntimeError(f"AbortRelay did not become ready at {relay_socket}")



def _spawn_supervisor(
    *,
    mode: str,
    selected_test: str | None = None,
    start_run_payload: dict[str, Any] | None = None,
    abort_relay_socket: str | None = None,
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

    if abort_relay_socket:
        cmd.extend(["--abort-relay-socket", abort_relay_socket])

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

    abort_relay_process: subprocess.Popen[str] | None = None
    abort_relay_socket: Path | None = None
    try:
        abort_relay_process, abort_relay_socket = _spawn_abort_relay()
        return _spawn_supervisor(
            mode="live",
            start_run_payload=start_run_payload,
            abort_relay_socket=str(abort_relay_socket),
        )
    except Exception as exc:
        QMessageBox.critical(
            None,
            "Abort Relay Launch Error",
            "Failed to launch AbortRelay for the live GUI session.\n\n"
            f"Error: {exc}",
        )
        return 1
    finally:
        if abort_relay_process is not None:
            _terminate_process(abort_relay_process, label="abort relay")
            _wait_for_process_exit(abort_relay_process, timeout_s=2.0)
            if abort_relay_process.poll() is None:
                _kill_process(abort_relay_process, label="abort relay")
                _wait_for_process_exit(abort_relay_process, timeout_s=1.0)
        if abort_relay_socket is not None:
            try:
                if abort_relay_socket.exists():
                    abort_relay_socket.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
