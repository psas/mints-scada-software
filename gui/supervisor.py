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


def _request_backend_state_snapshot(backend_socket: str) -> dict[str, Any] | None:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.5)
            sock.connect(backend_socket)
            request = {"type": "request_full_state", "payload": {}}
            wire = json.dumps(request, ensure_ascii=False, sort_keys=False) + "\n"
            sock.sendall(wire.encode("utf-8"))
            buffer = ""
            deadline = time.monotonic() + 1.5
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
                    if not isinstance(decoded, dict):
                        continue
                    message_type = decoded.get("type")
                    payload = decoded.get("payload", {})
                    if message_type == "state_snapshot" and isinstance(payload, dict):
                        return payload
    except Exception as exc:
        log.debug("GuiSupervisor backend state query failed: %s", exc)
        return None
    return None


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

    def refresh_recording_state(force: bool = False) -> bool:
        nonlocal last_recording_state, last_backend_poll_monotonic
        now = time.monotonic()
        if not force and now - last_backend_poll_monotonic < _BACKEND_STATE_POLL_S:
            return last_recording_state

        snapshot = _request_backend_state_snapshot(backend_socket)
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
