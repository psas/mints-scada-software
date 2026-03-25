#!/usr/bin/env python3
"""Background process that watches for shutdown signal and kills all tracked processes."""

import logging
import os
import signal
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _shutdown_signal_file() -> Path:
    return _project_root() / ".shutdown_signal"


def _application_pid_file() -> Path:
    return _project_root() / ".applicationpid"


def kill_all_application_processes() -> None:
    """Kill all processes listed in .applicationpid file."""
    pid_file = _application_pid_file()
    if not pid_file.exists():
        log.info("No .applicationpid file found, nothing to kill")
        return

    pids_to_kill = []
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
                pids_to_kill.append((pid, label))
            except ValueError:
                log.warning("Invalid PID in .applicationpid: %s", line)
    except Exception as exc:
        log.error("Failed to read .applicationpid: %s", exc)
        return

    # First pass: SIGTERM (graceful)
    for pid, label in pids_to_kill:
        try:
            os.kill(pid, signal.SIGTERM)
            log.info("Sent SIGTERM to %s (pid=%s)", label, pid)
        except ProcessLookupError:
            log.debug("Process %s (pid=%s) already dead", label, pid)
        except Exception as exc:
            log.warning("Failed to kill %s (pid=%s): %s", label, pid, exc)

    # Wait a bit for graceful shutdown
    time.sleep(2.0)

    # Second pass: SIGKILL (force)
    for pid, label in pids_to_kill:
        try:
            os.kill(pid, 0)  # Check if still alive
            os.kill(pid, signal.SIGKILL)
            log.warning("Sent SIGKILL to %s (pid=%s)", label, pid)
        except ProcessLookupError:
            pass  # Already dead, good
        except Exception as exc:
            log.warning("Failed to force-kill %s (pid=%s): %s", label, pid, exc)

    # Clean up .applicationpid
    try:
        pid_file.unlink()
        log.info("Deleted .applicationpid")
    except Exception as exc:
        log.warning("Failed to delete .applicationpid: %s", exc)


def watch_for_shutdown_signal() -> None:
    """Watch for shutdown signal file and kill all processes when it appears."""
    signal_file = _shutdown_signal_file()
    
    log.info("Shutdown watcher started, watching for %s", signal_file)
    
    try:
        while True:
            if signal_file.exists():
                log.warning("Shutdown signal detected! Killing all application processes...")
                
                # Remove signal file first
                try:
                    signal_file.unlink()
                except Exception as exc:
                    log.warning("Failed to remove shutdown signal file: %s", exc)
                
                # Kill everything
                kill_all_application_processes()
                
                log.info("Shutdown watcher exiting after cleanup")
                sys.exit(0)
            
            time.sleep(0.25)
    except KeyboardInterrupt:
        log.info("Shutdown watcher interrupted")
        sys.exit(0)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [shutdown_watcher] [%(levelname)s] %(message)s",
    )
    
    watch_for_shutdown_signal()
    return 0


if __name__ == "__main__":
    sys.exit(main())
