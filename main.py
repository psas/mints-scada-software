# main.py

"""Launch and supervise live or playback GUI sessions.

This module is the project-level entrypoint that coordinates checklist-driven
startup, service readiness, supervisor launch, and end-of-session cleanup. It
owns the top-level session choreography for backend, gateway, abort relay, and
GUI supervisor processes.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import settings
from PyQt5.QtWidgets import QApplication, QMessageBox

from gui import ChecklistWindow, QLoggingHandler

log = logging.getLogger(__name__)

_SERVICE_SOCKET_TIMEOUT_S = 10.0


def _project_root() -> Path:
    """Return the repository root directory for the launcher process.

    Returns:
        Absolute path to the directory containing this entrypoint module.
    """
    return Path(__file__).resolve().parent


def _dev_dir() -> Path:
    """Return the directory used for launcher-managed development artifacts.

    Returns:
        Path to the ``.dev`` directory under the project root.
    """
    return _project_root() / ".dev"


def _application_pid_file() -> Path:
    """Return the PID registry file used by shutdown cleanup.

    Returns:
        Path to the project-level ``.applicationpid`` file.
    """
    return _project_root() / ".applicationpid"


def _shutdown_signal_file() -> Path:
    """Return the file watched by the shutdown watcher process.

    Returns:
        Path to the project-level ``.shutdown_signal`` marker file.
    """
    return _project_root() / ".shutdown_signal"


def _backend_socket_path() -> Path:
    """Return the backend IPC socket path.

    Returns:
        Path to the backend service Unix domain socket.
    """
    return _project_root() / ".backend_service.sock"


def _gateway_socket_path() -> Path:
    """Return the gateway IPC socket path.

    Returns:
        Path to the gateway service Unix domain socket.
    """
    return _project_root() / ".gateway_service.sock"


def _backend_pid_file() -> Path:
    """Return the PID file used for the backend service.

    Returns:
        Path to the backend PID file under ``.dev``.
    """
    return _dev_dir() / "backend.pid"


def _gateway_pid_file() -> Path:
    """Return the PID file used for the gateway service.

    Returns:
        Path to the gateway PID file under ``.dev``.
    """
    return _dev_dir() / "gateway.pid"


def _register_pid(pid: int, label: str) -> None:
    """Append a process record to the application PID registry.

    Args:
        pid: Process ID to register.
        label: Human-readable process label written alongside the PID.

    Returns:
        None.
    """
    try:
        with _application_pid_file().open("a") as f:
            f.write(f"{pid} {label}\n")
        log.debug("Registered %s pid=%s to application pid file", label, pid)
    except Exception as exc:
        log.warning("Failed to register %s pid=%s: %s", label, pid, exc)


def _encode_json_arg(payload: dict[str, Any] | None) -> str | None:
    """Encode a JSON payload for transport through a command-line argument.

    Args:
        payload: JSON-serializable payload to encode.

    Returns:
        URL-safe base64 text for the encoded JSON payload, or None when the
        payload is empty.
    """
    if not payload:
        return None
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _configure_logging() -> QLoggingHandler:
    """Configure launcher logging for file, stderr, and Qt log display.

    Returns:
        The Qt logging handler attached to the root logging configuration.
    """
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
    """Resolve the GUI supervisor script path.

    Returns:
        Absolute path to ``gui/supervisor.py``.

    Raises:
        FileNotFoundError: The supervisor script is missing from the expected
            project location.
    """
    script_path = _project_root() / "gui" / "supervisor.py"
    if not script_path.is_file():
        raise FileNotFoundError(f"Missing GUI supervisor script: {script_path}")
    return script_path


def _abort_relay_script() -> Path:
    """Resolve the abort relay script path.

    Returns:
        Absolute path to ``gui/abort_relay.py``.

    Raises:
        FileNotFoundError: The abort relay script is missing from the expected
            project location.
    """
    script_path = _project_root() / "gui" / "abort_relay.py"
    if not script_path.is_file():
        raise FileNotFoundError(f"Missing AbortRelay script: {script_path}")
    return script_path


def _ping_abort_relay(socket_path: Path, *, timeout_s: float = 0.75) -> bool:
    """Check whether the abort relay socket responds to a ping request.

    Args:
        socket_path: Unix domain socket exposed by the abort relay process.
        timeout_s: Overall timeout for connect, send, and receive operations.

    Returns:
        True when the relay returns a ``pong`` response before the timeout,
        otherwise False.
    """
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout_s)
            sock.connect(str(socket_path))
            wire = (
                json.dumps(
                    {"type": "ping", "payload": {}}, ensure_ascii=False, sort_keys=False
                )
                + "\n"
            )
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
    """Start the abort relay process and wait for its relay socket to become ready.

    Returns:
        A tuple of the spawned process handle and the ready relay socket path.

    Raises:
        RuntimeError: The relay exits early or does not become ready before the
            startup deadline.
        FileNotFoundError: The relay script is missing.
    """
    script_path = _abort_relay_script()
    gateway_socket = _gateway_socket_path()

    socket_dir = Path(tempfile.gettempdir()) / "mints_scada_abort"
    socket_dir.mkdir(parents=True, exist_ok=True)
    relay_socket = socket_dir / f"gui_abort_relay_{os.getpid()}.sock"
    if relay_socket.exists():
        relay_socket.unlink()

    cmd = [
        sys.executable,
        str(script_path),
        "--gateway-socket",
        str(gateway_socket),
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
    _register_pid(process.pid, "abort_relay")
    log.info(
        "Spawned AbortRelay pid=%s socket=%s gateway=%s",
        process.pid,
        relay_socket,
        gateway_socket,
    )

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
    """Start the GUI supervisor for a live or playback session.

    Args:
        mode: Session mode passed to the supervisor.
        selected_test: Playback run identifier when launching playback mode.
        start_run_payload: Checklist-derived live run metadata forwarded to the
            supervisor for deferred run start handling.
        abort_relay_socket: Relay socket path forwarded to live-mode supervisor
            processes.

    Returns:
        The supervisor process exit code. Returns 130 when the launcher is
        interrupted and the supervisor is terminated locally.

    Raises:
        FileNotFoundError: The supervisor script is missing.
    """
    script_path = _supervisor_script()
    socket_path = _backend_socket_path()

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
    _register_pid(process.pid, f"supervisor_{mode}")
    log.info("Spawned GUI supervisor pid=%s for mode=%s", process.pid, mode)

    try:
        exit_code = process.wait()
        return exit_code
    except KeyboardInterrupt:
        log.info("Launcher interrupted; terminating GUI supervisor pid=%s", process.pid)
        _terminate_process(process, label="gui supervisor")
        _wait_for_process_exit(process, timeout_s=2.0)
        if process.poll() is None:
            _kill_process(process, label="gui supervisor")
            _wait_for_process_exit(process, timeout_s=1.0)
        return 130


def _terminate_process(process: subprocess.Popen[str], *, label: str) -> None:
    """Request graceful termination of a subprocess when it is still running.

    Args:
        process: Process handle to terminate.
        label: Human-readable label used for logging.

    Returns:
        None.
    """
    if process.poll() is not None:
        return
    try:
        log.info("Terminating %s pid=%s", label, process.pid)
        process.terminate()
    except Exception as exc:
        log.warning("Failed to terminate %s pid=%s: %s", label, process.pid, exc)


def _kill_process(process: subprocess.Popen[str], *, label: str) -> None:
    """Force-kill a subprocess when it is still running.

    Args:
        process: Process handle to kill.
        label: Human-readable label used for logging.

    Returns:
        None.
    """
    if process.poll() is not None:
        return
    try:
        log.warning("Killing %s pid=%s", label, process.pid)
        process.kill()
    except Exception as exc:
        log.warning("Failed to kill %s pid=%s: %s", label, process.pid, exc)


def _wait_for_process_exit(process: subprocess.Popen[str], *, timeout_s: float) -> None:
    """Wait for a subprocess to exit up to a bounded timeout.

    Args:
        process: Process handle to wait on.
        timeout_s: Maximum number of seconds to wait.

    Returns:
        None.
    """
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        pass


def _request_backend_shutdown() -> None:
    """Ask the backend service to shut down through its IPC socket.

    Returns:
        None.
    """
    socket_path = _backend_socket_path()
    if not socket_path.exists():
        log.debug("Backend socket not found, assuming backend already stopped")
        return

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)
            sock.connect(str(socket_path))
            request = {"type": "shutdown_service", "payload": {}}
            wire = json.dumps(request, ensure_ascii=False, sort_keys=False) + "\n"
            sock.sendall(wire.encode("utf-8"))
            log.info("Requested backend service shutdown")
            time.sleep(0.5)
    except Exception as exc:
        log.debug("Failed to request backend shutdown via IPC: %s", exc)


def _write_pid_file(pid_file: Path, pid: int) -> None:
    """Write a single PID into a PID file.

    Args:
        pid_file: PID file to update.
        pid: Process ID to store.

    Returns:
        None.
    """
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(f"{pid}\n")


def _read_pid_file(pid_file: Path) -> int | None:
    """Read an integer PID from a PID file when present and valid.

    Args:
        pid_file: PID file to inspect.

    Returns:
        The parsed PID, or None when the file is missing, empty, unreadable, or
        contains invalid text.
    """
    try:
        raw = pid_file.read_text().strip()
    except FileNotFoundError:
        return None
    except Exception as exc:
        log.warning("Failed to read pid file %s: %s", pid_file, exc)
        return None

    if not raw:
        return None

    try:
        return int(raw)
    except ValueError:
        log.warning("Invalid pid file contents in %s: %r", pid_file, raw)
        return None


def _is_pid_alive(pid: int) -> bool:
    """Return whether a process ID appears to be alive.

    Args:
        pid: Process ID to probe with signal 0.

    Returns:
        True when the process exists and is signalable, otherwise False.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return False


def _remove_file_if_exists(path: Path) -> None:
    """Remove a file or Unix socket path when it exists.

    Args:
        path: Filesystem path to remove.

    Returns:
        None.
    """
    try:
        if path.exists() or path.is_socket():
            path.unlink()
    except FileNotFoundError:
        pass
    except Exception as exc:
        log.debug("Failed to remove %s: %s", path, exc)


def _can_connect_unix_socket(socket_path: Path, *, timeout_s: float = 0.25) -> bool:
    """Return whether a Unix domain socket accepts a connection.

    Args:
        socket_path: Socket path to probe.
        timeout_s: Connect timeout used for the probe.

    Returns:
        True when the socket accepts a connection, otherwise False.
    """
    if not socket_path.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout_s)
            sock.connect(str(socket_path))
            return True
    except Exception:
        return False


def _wait_for_socket(socket_path: Path, *, timeout_s: float) -> bool:
    """Poll until a Unix socket becomes connectable or the timeout expires.

    Args:
        socket_path: Socket path to wait for.
        timeout_s: Maximum number of seconds to wait.

    Returns:
        True when the socket becomes connectable before the deadline, otherwise
        False.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _can_connect_unix_socket(socket_path, timeout_s=0.25):
            return True
        time.sleep(0.1)
    return False


def _spawn_service_process(
    *,
    module_name: str,
    label: str,
    pid_file: Path,
    socket_path: Path,
) -> subprocess.Popen[str]:
    """Start one service module as a subprocess and record its PID.

    Args:
        module_name: Importable module name passed to ``python -m``.
        label: Human-readable service label used for logging and PID registry.
        pid_file: PID file updated with the spawned process ID.
        socket_path: Expected socket path for the spawned service. This value is
            used only for call-site clarity.

    Returns:
        The spawned subprocess handle.
    """
    cmd = [sys.executable, "-m", module_name]
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    process = subprocess.Popen(
        cmd,
        cwd=str(_project_root()),
        env=env,
        text=True,
        start_new_session=False,
    )
    _write_pid_file(pid_file, process.pid)
    _register_pid(process.pid, label)
    log.info("Spawned %s pid=%s", label, process.pid)
    return process


def _ensure_service_running(
    *,
    module_name: str,
    label: str,
    pid_file: Path,
    socket_path: Path,
) -> tuple[subprocess.Popen[str] | None, bool]:
    """Ensure a backend-style service is alive and serving its socket.

    This helper reuses an existing reachable service when possible, waits for an
    already-running PID to expose its socket, or starts a fresh subprocess after
    cleaning stale PID and socket artifacts.

    Args:
        module_name: Importable module name passed to ``python -m`` when a new
            subprocess must be started.
        label: Human-readable service label used for logging.
        pid_file: PID file associated with the service.
        socket_path: Expected Unix socket path for the service.

    Returns:
        A tuple of ``(process, started_new_process)``. ``process`` is None when
        an existing service instance was reused.

    Raises:
        RuntimeError: The service is alive but never makes its socket ready, or
            a newly spawned instance fails to become ready in time.
    """
    pid = _read_pid_file(pid_file)

    if _can_connect_unix_socket(socket_path, timeout_s=0.25):
        if pid is not None and not _is_pid_alive(pid):
            log.info("Removing stale %s pid file %s", label, pid_file)
            _remove_file_if_exists(pid_file)
        log.info("Using existing %s via socket %s", label, socket_path)
        return None, False

    if pid is not None and _is_pid_alive(pid):
        log.info("%s pid=%s is alive; waiting for socket %s", label, pid, socket_path)
        if _wait_for_socket(socket_path, timeout_s=_SERVICE_SOCKET_TIMEOUT_S):
            return None, False
        raise RuntimeError(
            f"{label.capitalize()} pid={pid} did not make socket ready: {socket_path}"
        )

    if pid is not None:
        log.info("Removing stale %s pid file %s", label, pid_file)
        _remove_file_if_exists(pid_file)

    if socket_path.exists():
        log.info("Removing stale %s socket %s", label, socket_path)
        _remove_file_if_exists(socket_path)

    process = _spawn_service_process(
        module_name=module_name,
        label=label,
        pid_file=pid_file,
        socket_path=socket_path,
    )

    if _wait_for_socket(socket_path, timeout_s=_SERVICE_SOCKET_TIMEOUT_S):
        return process, True

    _terminate_process(process, label=label)
    _wait_for_process_exit(process, timeout_s=2.0)
    if process.poll() is None:
        _kill_process(process, label=label)
        _wait_for_process_exit(process, timeout_s=1.0)

    _remove_file_if_exists(pid_file)
    _remove_file_if_exists(socket_path)
    raise RuntimeError(f"{label.capitalize()} did not become ready at {socket_path}")


def _ensure_backend_running() -> tuple[subprocess.Popen[str] | None, bool]:
    """Ensure the backend service is available for the current session.

    Returns:
        The result from ``_ensure_service_running`` for ``backend.main``.
    """
    return _ensure_service_running(
        module_name="backend.main",
        label="backend",
        pid_file=_backend_pid_file(),
        socket_path=_backend_socket_path(),
    )


def _ensure_gateway_running() -> tuple[subprocess.Popen[str] | None, bool]:
    """Ensure the gateway service is available for the current session.

    Returns:
        The result from ``_ensure_service_running`` for ``gateway.main``.
    """
    return _ensure_service_running(
        module_name="gateway.main",
        label="gateway",
        pid_file=_gateway_pid_file(),
        socket_path=_gateway_socket_path(),
    )


def _track_existing_service_pid(pid_file: Path, label: str) -> None:
    """Register an already-running service PID in the application PID registry.

    Args:
        pid_file: PID file to inspect.
        label: Human-readable service label to register.

    Returns:
        None.
    """
    pid = _read_pid_file(pid_file)
    if pid is None:
        return
    if not _is_pid_alive(pid):
        return
    _register_pid(pid, label)


def _signal_pid(pid: int, sig: int, *, label: str) -> None:
    """Send a Unix signal to a process ID for service cleanup.

    Args:
        pid: Target process ID.
        sig: Signal number to send.
        label: Human-readable process label used for logging.

    Returns:
        None.
    """
    try:
        os.kill(pid, sig)
        log.info("Sent signal %s to %s pid=%s", sig, label, pid)
    except ProcessLookupError:
        pass
    except Exception as exc:
        log.warning("Failed to signal %s pid=%s: %s", label, pid, exc)


def _cleanup_pid_backed_service(
    *,
    process: subprocess.Popen[str] | None,
    pid_file: Path,
    socket_path: Path,
    label: str,
    request_shutdown_first: bool = False,
) -> None:
    """Shut down a PID-backed service and remove stale launcher artifacts.

    Args:
        process: Process handle when this launcher started the service during
            the current session, otherwise None.
        pid_file: PID file associated with the service.
        socket_path: Socket path associated with the service.
        label: Human-readable service label used for logging.
        request_shutdown_first: Whether to attempt a graceful backend IPC
            shutdown before sending process signals.

    Returns:
        None.
    """
    if request_shutdown_first:
        _request_backend_shutdown()
        time.sleep(0.5)

    if process is not None:
        _wait_for_process_exit(process, timeout_s=2.5)
        if process.poll() is None:
            _terminate_process(process, label=label)
            _wait_for_process_exit(process, timeout_s=2.0)
        if process.poll() is None:
            _kill_process(process, label=label)
            _wait_for_process_exit(process, timeout_s=1.0)
    else:
        pid = _read_pid_file(pid_file)
        if pid is not None and _is_pid_alive(pid):
            _signal_pid(pid, signal.SIGTERM, label=label)
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and _is_pid_alive(pid):
                time.sleep(0.1)
            if _is_pid_alive(pid):
                _signal_pid(pid, signal.SIGKILL, label=label)

    _remove_file_if_exists(pid_file)
    if socket_path.exists() and not _can_connect_unix_socket(
        socket_path, timeout_s=0.2
    ):
        _remove_file_if_exists(socket_path)


def _cleanup_session_backend(process: subprocess.Popen[str] | None) -> None:
    """Clean up the backend service for a session-managed shutdown.

    Args:
        process: Backend process handle when started by this launcher, otherwise
            None.

    Returns:
        None.
    """
    _cleanup_pid_backed_service(
        process=process,
        pid_file=_backend_pid_file(),
        socket_path=_backend_socket_path(),
        label="backend",
        request_shutdown_first=True,
    )


def _cleanup_session_gateway(process: subprocess.Popen[str] | None) -> None:
    """Clean up the gateway service for a session-managed shutdown.

    Args:
        process: Gateway process handle when started by this launcher, otherwise
            None.

    Returns:
        None.
    """
    _cleanup_pid_backed_service(
        process=process,
        pid_file=_gateway_pid_file(),
        socket_path=_gateway_socket_path(),
        label="gateway",
        request_shutdown_first=False,
    )


def _trigger_shutdown_watcher() -> None:
    """Create the shutdown marker consumed by the shutdown watcher.

    Returns:
        None.
    """
    try:
        _shutdown_signal_file().write_text("1\n", encoding="utf-8")
        log.info("Created shutdown signal file for shutdown_watcher")
    except Exception as exc:
        log.warning("Failed to create shutdown signal file: %s", exc)


def main() -> int:
    """Run the top-level launcher flow for live or playback sessions.

    This creates the Qt application, shows the checklist/startup dialog,
    prepares required services for the selected mode, launches the GUI
    supervisor, and coordinates shutdown cleanup for session-managed processes.

    Returns:
        Process exit code for the launcher session.
    """
    app = QApplication(sys.argv)
    _configure_logging()
    log.debug("Starting user GUI launcher entrypoint")

    backend_process: subprocess.Popen[str] | None = None
    backend_session_managed = False
    gateway_process: subprocess.Popen[str] | None = None
    gateway_session_managed = False
    abort_relay_process: subprocess.Popen[str] | None = None
    abort_relay_socket: Path | None = None
    session_should_shutdown_all = False

    def _prepare_live_services_for_setup(
        live_metadata: dict[str, Any],
    ) -> tuple[bool, str]:
        """Start live-mode services from the checklist live-setup callback.

        Args:
            live_metadata: Checklist-collected live run metadata. The callback
                does not consume the payload directly; it only ensures the live
                service stack is ready before session launch continues.

        Returns:
            A ``(success, message)`` tuple describing whether live services are
            ready and what status text the checklist should display.
        """
        nonlocal backend_process, backend_session_managed
        nonlocal gateway_process, gateway_session_managed
        nonlocal session_should_shutdown_all

        try:
            if not gateway_session_managed:
                gateway_process, _ = _ensure_gateway_running()
                gateway_session_managed = True
                if gateway_process is None:
                    _track_existing_service_pid(_gateway_pid_file(), "gateway")

            if not backend_session_managed:
                backend_process, _ = _ensure_backend_running()
                backend_session_managed = True
                if backend_process is None:
                    _track_existing_service_pid(_backend_pid_file(), "backend")

            session_should_shutdown_all = True
            return True, "Live services are ready. Launching session..."
        except Exception as exc:
            log.exception("Failed to prepare live services from Live Setup")
            return False, f"Failed to start live services: {exc}"

    try:
        checklist = ChecklistWindow(
            settings.sender,
            live_startup_callback=_prepare_live_services_for_setup,
        )
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

            if not backend_session_managed:
                backend_process, _ = _ensure_backend_running()
                backend_session_managed = True
                if backend_process is None:
                    _track_existing_service_pid(_backend_pid_file(), "backend")

            session_should_shutdown_all = True
            log.info(
                "Launching playback GUI supervisor for run=%s (backend session managed=%s)",
                selected_test,
                backend_session_managed,
            )
            supervisor_exit_code = _spawn_supervisor(
                mode="playback", selected_test=selected_test
            )
            return supervisor_exit_code

        live_metadata = dict(checklist.live_run_metadata or {}) or None
        if not live_metadata:
            QMessageBox.critical(
                None,
                "Live Start Error",
                "Live mode requires run metadata before the operator windows can open.",
            )
            return 1

        if not gateway_session_managed:
            gateway_process, _ = _ensure_gateway_running()
            gateway_session_managed = True
            if gateway_process is None:
                _track_existing_service_pid(_gateway_pid_file(), "gateway")

        if not backend_session_managed:
            backend_process, _ = _ensure_backend_running()
            backend_session_managed = True
            if backend_process is None:
                _track_existing_service_pid(_backend_pid_file(), "backend")

        session_should_shutdown_all = True
        log.info(
            "Launching live GUI supervisor without pre-starting backend recording. "
            "Checklist metadata will be passed through to the controller Start Recording button: %s",
            live_metadata,
        )

        abort_relay_process, abort_relay_socket = _spawn_abort_relay()
        supervisor_exit_code = _spawn_supervisor(
            mode="live",
            selected_test=None,
            start_run_payload=live_metadata,
            abort_relay_socket=str(abort_relay_socket),
        )
        return supervisor_exit_code

    except Exception as exc:
        QMessageBox.critical(
            None,
            "GUI Launch Error",
            "The GUI support process failed to launch.\n\n" f"Error: {exc}",
        )
        return 1

    finally:
        if session_should_shutdown_all:
            _trigger_shutdown_watcher()
            time.sleep(0.8)

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

        if not session_should_shutdown_all and backend_session_managed:
            _cleanup_session_backend(backend_process)

        if not session_should_shutdown_all and gateway_session_managed:
            _cleanup_session_gateway(gateway_process)


if __name__ == "__main__":
    raise SystemExit(main())
