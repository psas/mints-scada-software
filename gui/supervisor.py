from __future__ import annotations

import argparse
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
from typing import Any

log = logging.getLogger(__name__)

_MONITOR_POLL_S = 0.25
_BACKEND_STATE_POLL_S = 0.5


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _application_pid_file() -> Path:
    return _project_root() / ".applicationpid"


def _register_pid(pid: int, label: str) -> None:
    """Register a process PID to the application PID file for cleanup."""
    try:
        with _application_pid_file().open("a") as f:
            f.write(f"{pid} {label}\n")
        log.debug("Registered %s pid=%s to application pid file", label, pid)
    except Exception as exc:
        log.warning("Failed to register %s pid=%s: %s", label, pid, exc)


def _configure_logging() -> None:
    formatstr = "%(asctime)s [%(name)-16.16s] [%(levelname)-5.5s] %(message)s"
    log_dir = _project_root() / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG,
        format=formatstr,
        handlers=[
            logging.FileHandler(log_dir / "debug.log"),
            logging.StreamHandler(),
        ],
    )


def _window_host_script() -> Path:
    script_path = _project_root() / "gui" / "window_host.py"
    if not script_path.is_file():
        raise FileNotFoundError(f"Missing window host script: {script_path}")
    return script_path


def _decode_json_arg(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        raise ValueError(f"Failed to decode JSON argument: {exc}") from exc
    return None


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


def _dummy_supervisor_socket() -> str:
    socket_dir = Path(tempfile.gettempdir()) / "mints_scada_supervisor_dummy"
    socket_dir.mkdir(parents=True, exist_ok=True)
    return str(socket_dir / f"noop_supervisor_{os.getpid()}.sock")


def _spawn_window_process(
    *,
    mode: str,
    window_kind: str,
    backend_socket: str,
    selected_test: str | None,
    pending_start_run_payload: dict[str, Any] | None,
    abort_relay_socket: str | None,
) -> subprocess.Popen[str]:
    script_path = _window_host_script()
    cmd = [
        sys.executable,
        str(script_path),
        "--mode",
        mode,
        "--window-kind",
        window_kind,
        "--backend-socket",
        backend_socket,
        "--supervisor-socket",
        _dummy_supervisor_socket(),
    ]
    if selected_test:
        cmd.extend(["--selected-test", selected_test])
    if abort_relay_socket:
        cmd.extend(["--abort-relay-socket", abort_relay_socket])

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env["MINTS_WINDOW_MODE"] = mode
    env["MINTS_WINDOW_KIND"] = window_kind
    if abort_relay_socket:
        env["MINTS_ABORT_RELAY_SOCKET"] = abort_relay_socket
    if pending_start_run_payload is not None:
        encoded = base64.urlsafe_b64encode(
            json.dumps(pending_start_run_payload, ensure_ascii=False, sort_keys=False).encode("utf-8")
        ).decode("ascii")
        env["MINTS_PENDING_START_RUN_B64"] = encoded
    else:
        env.pop("MINTS_PENDING_START_RUN_B64", None)

    process = subprocess.Popen(
        cmd,
        cwd=str(_project_root()),
        env=env,
        text=True,
        start_new_session=False,
    )
    _register_pid(process.pid, f"{mode}_{window_kind}_window")
    log.info("GuiSupervisor spawned %s %s window pid=%s", mode, window_kind, process.pid)
    return process


class _BackendProbe:
    """Persistent socket probe for supervisor backend state polling.

    Keeps a single long-lived connection to the backend so that repeated
    state queries do not generate connect/disconnect noise in the event
    stream.  Sends a hello on first connect so the backend can identify
    this connection as a supervisor probe.
    """

    _DRAIN_TIMEOUT_S = 2.0
    _READ_TIMEOUT_S = 3.0
    _MAX_LINES = 20

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._reader: Any = None
        self._writer: Any = None

    def query_state(self, backend_socket: str) -> dict[str, Any] | None:
        try:
            self._ensure_connected(backend_socket)
            return self._send_state_request()
        except Exception as exc:
            log.debug("GuiSupervisor backend state query failed: %s", exc)
            self.close()
            return None

    def close(self) -> None:
        for obj in (self._writer, self._reader, self._sock):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass
        self._sock = None
        self._reader = None
        self._writer = None

    def _read_until(self, target_type: str, *, timeout_s: float) -> dict[str, Any] | None:
        """Read lines until a message of *target_type* arrives or timeout.

        Other message types are silently skipped so the probe is not
        sensitive to the number or order of non-target messages the
        backend sends (hello_ack, backend_status, structured_event, etc.).
        """
        reader = self._reader
        sock = self._sock
        if reader is None or sock is None:
            return None

        prev_timeout = sock.gettimeout()
        sock.settimeout(timeout_s)
        try:
            for _ in range(self._MAX_LINES):
                line = reader.readline()
                if not line:
                    raise ConnectionError("Backend closed connection")
                line = line.strip()
                if not line:
                    continue
                try:
                    decoded = json.loads(line)
                except Exception:
                    continue
                if isinstance(decoded, dict) and decoded.get("type") == target_type:
                    payload = decoded.get("payload", {})
                    return payload if isinstance(payload, dict) else {}
        except socket.timeout:
            log.debug("GuiSupervisor _read_until(%s) timed out", target_type)
            return None
        finally:
            sock.settimeout(prev_timeout)
        return None

    def _ensure_connected(self, backend_socket: str) -> None:
        if self._sock is not None:
            return

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self._READ_TIMEOUT_S)
        sock.connect(backend_socket)
        reader = sock.makefile("r", encoding="utf-8")
        writer = sock.makefile("w", encoding="utf-8")

        self._sock = sock
        self._reader = reader
        self._writer = writer

        # Send hello so the backend registers this as a known client
        # rather than an anonymous probe.
        hello = {
            "type": "hello",
            "payload": {
                "client_name": "supervisor-probe",
                "logical_client_id": f"gui:supervisor:probe:{os.getpid()}",
                "window_role": "supervisor_probe",
                "mode": "live",
                "window_kind": "supervisor",
                "pid": os.getpid(),
            },
        }
        writer.write(json.dumps(hello, ensure_ascii=False) + "\n")
        writer.flush()

        # Drain the hello handshake responses (hello_ack, backend_status,
        # possibly others).  We don't need the content — just ensure the
        # read buffer is empty before the first real query.
        self._read_until("hello_ack", timeout_s=self._DRAIN_TIMEOUT_S)

    def _send_state_request(self) -> dict[str, Any] | None:
        writer = self._writer
        if writer is None:
            return None
        request = json.dumps({"type": "request_full_state", "payload": {}}, ensure_ascii=False) + "\n"
        writer.write(request)
        writer.flush()
        return self._read_until("state_snapshot", timeout_s=self._READ_TIMEOUT_S)


def _extract_recording_active_from_snapshot(snapshot: dict[str, Any] | None) -> bool | None:
    if not isinstance(snapshot, dict):
        return None

    candidate_paths = [
        ("run", "is_running"),
        ("run_state", "is_running"),
        ("run_controller", "is_running"),
    ]
    for path in candidate_paths:
        cursor: Any = snapshot
        valid_path = True
        for key in path:
            if isinstance(cursor, dict) and key in cursor:
                cursor = cursor[key]
            else:
                valid_path = False
                break
        if valid_path and isinstance(cursor, bool):
            return cursor

    run_section = snapshot.get("run")
    if isinstance(run_section, dict):
        status = run_section.get("status")
        if isinstance(status, str):
            lowered = status.strip().lower()
            if lowered in {"running", "active", "recording"}:
                return True
            if lowered in {"idle", "completed", "stopped", "not_running", "finished"}:
                return False

        current_run_id = run_section.get("run_id") or run_section.get("active_run_id")
        if isinstance(current_run_id, str) and current_run_id.strip():
            completed = run_section.get("completed")
            if isinstance(completed, bool):
                return not completed

    current_run = snapshot.get("current_run")
    if isinstance(current_run, dict):
        run_id = current_run.get("run_id")
        if isinstance(run_id, str) and run_id.strip():
            return True

    return None


def _shutdown_remaining(children: dict[str, subprocess.Popen[str]], *, skip: str | None = None) -> None:
    for name, process in children.items():
        if skip is not None and name == skip:
            continue
        _terminate_process(process, label=f"{name} window")
    for name, process in children.items():
        if skip is not None and name == skip:
            continue
        _wait_for_process_exit(process, timeout_s=2.0)
        if process.poll() is None:
            _kill_process(process, label=f"{name} window")
            _wait_for_process_exit(process, timeout_s=1.0)


def _monitor_session(
    *,
    mode: str,
    backend_socket: str,
    selected_test: str | None,
    pending_start_run_payload: dict[str, Any] | None,
    abort_relay_socket: str | None,
    child_map: dict[str, subprocess.Popen[str]],
) -> int:
    last_recording_state = False
    last_backend_poll_monotonic = 0.0
    probe = _BackendProbe()

    def refresh_recording_state(force: bool = False) -> bool:
        nonlocal last_recording_state, last_backend_poll_monotonic
        now = time.monotonic()
        if not force and now - last_backend_poll_monotonic < _BACKEND_STATE_POLL_S:
            return last_recording_state

        snapshot = probe.query_state(backend_socket)
        extracted = _extract_recording_active_from_snapshot(snapshot)
        if extracted is not None and extracted != last_recording_state:
            log.info(
                "GuiSupervisor recording_active changed: %s -> %s",
                last_recording_state,
                extracted,
            )
            last_recording_state = extracted
        last_backend_poll_monotonic = now
        return last_recording_state

    # Only live mode needs backend recording-state polling.
    if mode == "live":
        refresh_recording_state(force=True)

    try:
        while True:
            if mode == "live":
                recording_active = refresh_recording_state()
            else:
                recording_active = False

            for name, process in list(child_map.items()):
                return_code = process.poll()
                if return_code is None:
                    continue

                if mode == "live" and recording_active:
                    log.warning(
                        "%s window exited with code=%s while recording is active; respawning",
                        name,
                        return_code,
                    )
                    child_map[name] = _spawn_window_process(
                        mode=mode,
                        window_kind=name,
                        backend_socket=backend_socket,
                        selected_test=selected_test,
                        pending_start_run_payload=pending_start_run_payload,
                        abort_relay_socket=abort_relay_socket,
                    )
                    break

                log.info(
                    "%s window exited with code=%s; shutting down remaining GUI windows for this %s session",
                    name,
                    return_code,
                    mode,
                )
                _shutdown_remaining(child_map, skip=name)
                return 0

            time.sleep(_MONITOR_POLL_S)
    except KeyboardInterrupt:
        log.info("GuiSupervisor interrupted; terminating child GUI windows")
        _shutdown_remaining(child_map)
        return 130
    finally:
        probe.close()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch and monitor split minTS GUI windows")
    parser.add_argument("--mode", choices=("live", "playback"), required=True)
    parser.add_argument("--backend-socket", required=True)
    parser.add_argument("--selected-test")
    parser.add_argument("--start-run-payload-b64")
    parser.add_argument("--abort-relay-socket")
    return parser


def main() -> int:
    _configure_logging()
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.mode == "playback" and not args.selected_test:
        parser.error("--selected-test is required for playback mode")

    pending_start_run_payload = _decode_json_arg(args.start_run_payload_b64) if args.mode == "live" else None

    processes: dict[str, subprocess.Popen[str]] = {}
    try:
        processes["controller"] = _spawn_window_process(
            mode=args.mode,
            window_kind="controller",
            backend_socket=args.backend_socket,
            selected_test=args.selected_test,
            pending_start_run_payload=pending_start_run_payload,
            abort_relay_socket=args.abort_relay_socket,
        )
        processes["scada"] = _spawn_window_process(
            mode=args.mode,
            window_kind="scada",
            backend_socket=args.backend_socket,
            selected_test=args.selected_test,
            pending_start_run_payload=pending_start_run_payload,
            abort_relay_socket=args.abort_relay_socket,
        )
        return _monitor_session(
            mode=args.mode,
            backend_socket=args.backend_socket,
            selected_test=args.selected_test,
            pending_start_run_payload=pending_start_run_payload,
            abort_relay_socket=args.abort_relay_socket,
            child_map=processes,
        )
    finally:
        _shutdown_remaining(processes)


if __name__ == "__main__":
    sys.exit(main())
