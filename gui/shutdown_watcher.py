#!/usr/bin/env python3
# gui/shutdown_watcher.py

"""Watch for launcher shutdown signals and tear down tracked application processes.

This module runs as a small background process that waits for the project-root
``.shutdown_signal`` file. When the signal appears, it terminates the processes
listed in ``.applicationpid`` and removes backend and gateway pid/socket
artifacts used by the multi-process launcher.
"""

import logging
import os
import signal
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)


def _project_root() -> Path:
    """Return the repository root derived from this module location.

    Returns:
        Absolute path to the project root directory.
    """
    return Path(__file__).resolve().parent.parent


def _shutdown_signal_file() -> Path:
    """Return the project-root shutdown signal file path.

    Returns:
        Path to ``.shutdown_signal`` in the project root.
    """
    return _project_root() / ".shutdown_signal"


def _application_pid_file() -> Path:
    """Return the tracked application pid registry path.

    Returns:
        Path to ``.applicationpid`` in the project root.
    """
    return _project_root() / ".applicationpid"


def _dev_dir() -> Path:
    """Return the directory that stores service runtime artifacts.

    Returns:
        Path to the project ``.dev`` directory.
    """
    return _project_root() / ".dev"


def _backend_socket_path() -> Path:
    """Return the backend service socket path.

    Returns:
        Path to ``.backend_service.sock`` in the project root.
    """
    return _project_root() / ".backend_service.sock"


def _gateway_socket_path() -> Path:
    """Return the gateway service socket path.

    Returns:
        Path to ``.gateway_service.sock`` in the project root.
    """
    return _project_root() / ".gateway_service.sock"


def _backend_pid_file() -> Path:
    """Return the backend service pid file path.

    Returns:
        Path to ``backend.pid`` under the project ``.dev`` directory.
    """
    return _dev_dir() / "backend.pid"


def _gateway_pid_file() -> Path:
    """Return the gateway service pid file path.

    Returns:
        Path to ``gateway.pid`` under the project ``.dev`` directory.
    """
    return _dev_dir() / "gateway.pid"


def _remove_if_exists(path: Path) -> None:
    """Delete a filesystem path when it currently exists.

    The existence check also treats Unix domain sockets as removable artifacts.

    Args:
        path: File or socket path to remove.

    Returns:
        None.
    """
    try:
        if path.exists() or path.is_socket():
            path.unlink()
            log.info("Deleted %s", path)
    except FileNotFoundError:
        pass
    except Exception as exc:
        log.warning("Failed to delete %s: %s", path, exc)


def cleanup_service_artifacts() -> None:
    """Remove backend and gateway pid/socket artifacts after shutdown cleanup.

    Returns:
        None.
    """
    _remove_if_exists(_backend_pid_file())
    _remove_if_exists(_gateway_pid_file())
    _remove_if_exists(_backend_socket_path())
    _remove_if_exists(_gateway_socket_path())


def kill_all_application_processes() -> None:
    """Terminate all tracked application processes except this watcher.

    The watcher reads ``.applicationpid``, deduplicates pid entries, skips its
    own pid and any explicit ``shutdown_watcher`` entry, then sends SIGTERM
    followed by SIGKILL to processes that remain alive. After the passes
    complete, it removes ``.applicationpid``.

    Returns:
        None.
    """
    pid_file = _application_pid_file()
    if not pid_file.exists():
        log.info("No .applicationpid file found, nothing to kill")
        return

    own_pid = os.getpid()
    pids_to_kill: list[tuple[int, str]] = []
    skipped_self: list[tuple[int, str]] = []
    seen: set[int] = set()

    try:
        lines = pid_file.read_text().splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if not parts:
                continue

            pid_str = parts[0]
            label = parts[1] if len(parts) > 1 else "unknown"

            try:
                pid = int(pid_str)
            except ValueError:
                log.warning("Invalid PID in .applicationpid: %s", line)
                continue

            if pid in seen:
                continue
            seen.add(pid)

            # Never kill the watcher itself. It will exit after cleanup.
            if pid == own_pid or label == "shutdown_watcher":
                skipped_self.append((pid, label))
                continue

            pids_to_kill.append((pid, label))
    except Exception as exc:
        log.error("Failed to read .applicationpid: %s", exc)
        return

    if skipped_self:
        log.info("Skipping self entries during watcher cleanup: %s", skipped_self)

    # First pass: SIGTERM (graceful)
    for pid, label in pids_to_kill:
        try:
            os.kill(pid, signal.SIGTERM)
            log.info("Sent SIGTERM to %s (pid=%s)", label, pid)
        except ProcessLookupError:
            log.debug("Process %s (pid=%s) already dead", label, pid)
        except Exception as exc:
            log.warning("Failed to terminate %s (pid=%s): %s", label, pid, exc)

    # Wait a bit for graceful shutdown
    time.sleep(2.0)

    # Second pass: SIGKILL (force)
    for pid, label in pids_to_kill:
        try:
            os.kill(pid, 0)  # Check if still alive
            os.kill(pid, signal.SIGKILL)
            log.warning("Sent SIGKILL to %s (pid=%s)", label, pid)
        except ProcessLookupError:
            pass  # Already dead
        except Exception as exc:
            log.warning("Failed to force-kill %s (pid=%s): %s", label, pid, exc)

    # Clean up application pid file
    try:
        pid_file.unlink()
        log.info("Deleted .applicationpid")
    except FileNotFoundError:
        pass
    except Exception as exc:
        log.warning("Failed to delete .applicationpid: %s", exc)


def watch_for_shutdown_signal() -> None:
    """Poll for the shutdown signal file and perform full process cleanup.

    When ``.shutdown_signal`` appears, this removes the signal file first,
    terminates tracked application processes, deletes backend and gateway
    runtime artifacts, and exits the watcher process.

    Returns:
        None.
    """
    signal_file = _shutdown_signal_file()

    log.info("Shutdown watcher started, watching for %s", signal_file)

    try:
        while True:
            if signal_file.exists():
                log.warning(
                    "Shutdown signal detected! Killing all application processes..."
                )

                # Remove signal file first so launcher can observe progress.
                try:
                    signal_file.unlink()
                    log.info("Deleted .shutdown_signal")
                except FileNotFoundError:
                    pass
                except Exception as exc:
                    log.warning("Failed to remove shutdown signal file: %s", exc)

                # Kill everything except this watcher.
                kill_all_application_processes()
                cleanup_service_artifacts()

                log.info("Shutdown watcher exiting after cleanup")
                sys.exit(0)

            time.sleep(0.25)
    except KeyboardInterrupt:
        log.info("Shutdown watcher interrupted")
        sys.exit(0)


def main() -> int:
    """Configure watcher logging and start the shutdown watch loop.

    Returns:
        Process exit status code.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [shutdown_watcher] [%(levelname)s] %(message)s",
    )

    watch_for_shutdown_signal()
    return 0


if __name__ == "__main__":
    sys.exit(main())
