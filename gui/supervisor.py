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
import threading
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gui import QLoggingHandler  # noqa: E402

log = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_S = 1.0
_HEARTBEAT_STALE_AFTER_S = 2.5
_MONITOR_POLL_S = 0.25
_BACKEND_STATE_POLL_S = 1.0
_RESPAWN_KILL_TIMEOUT_S = 2.0
_RESPAWN_LIMIT_WINDOW_S = 60.0
_RESPAWN_LIMIT_COUNT = 8


def _project_root() -> Path:
    return PROJECT_ROOT


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


def _decode_json_arg(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    raw = base64.urlsafe_b64decode(value.encode("ascii"))
    payload = json.loads(raw.decode("utf-8"))
    if isinstance(payload, dict):
        return payload
    raise ValueError("Decoded payload was not a JSON object")


def _window_host_script() -> Path:
    script_path = _project_root() / "gui" / "window_host.py"
    if not script_path.is_file():
        raise FileNotFoundError(f"Missing window host script: {script_path}")
    return script_path


class HeartbeatRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._windows: dict[str, dict[str, Any]] = {}

    def apply_message(self, payload: dict[str, Any]) -> None:
        window_role = str(payload.get("window_role") or "").strip()
        if not window_role:
            return

        now = time.monotonic()
        with self._lock:
            record = self._windows.setdefault(window_role, {})
            record["window_role"] = window_role
            record["window_kind"] = payload.get("window_kind")
            record["mode"] = payload.get("mode")
            record["pid"] = payload.get("pid")
            record["session_id"] = payload.get("session_id")
            record["last_message_type"] = payload.get("type")
            record["last_wall_time"] = payload.get("wall_time")
            record["last_monotonic"] = now

            if payload.get("type") == "hello":
                record["hello_count"] = int(record.get("hello_count", 0)) + 1
                log.info(
                    "GuiSupervisor registered %s pid=%s session=%s",
                    window_role,
                    payload.get("pid"),
                    payload.get("session_id"),
                )
            elif payload.get("type") == "heartbeat":
                record["heartbeat_count"] = int(record.get("heartbeat_count", 0)) + 1
            elif payload.get("type") == "goodbye":
                record["goodbye_count"] = int(record.get("goodbye_count", 0)) + 1
                log.info(
                    "GuiSupervisor received goodbye from %s pid=%s",
                    window_role,
                    payload.get("pid"),
                )

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(record) for _, record in sorted(self._windows.items())]

    def forget_role(self, window_role: str) -> None:
        with self._lock:
            self._windows.pop(window_role, None)


class HeartbeatServer:
    def __init__(self, *, socket_path: Path, registry: HeartbeatRegistry) -> None:
        self.socket_path = socket_path
        self.registry = registry
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._server_socket: socket.socket | None = None

    def start(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.socket_path.exists():
                self.socket_path.unlink()
        except FileNotFoundError:
            pass

        server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_socket.bind(str(self.socket_path))
        server_socket.listen(8)
        server_socket.settimeout(0.5)
        self._server_socket = server_socket

        self._thread = threading.Thread(
            target=self._run,
            name="gui-supervisor-heartbeat-server",
            daemon=True,
        )
        self._thread.start()
        log.info("GuiSupervisor heartbeat socket listening at %s", self.socket_path)

    def stop(self) -> None:
        self._stop_event.set()
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None

        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

        try:
            if self.socket_path.exists():
                self.socket_path.unlink()
        except Exception:
            pass

    def _run(self) -> None:
        assert self._server_socket is not None
        while not self._stop_event.is_set():
            try:
                conn, _ = self._server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stop_event.is_set():
                    break
                continue

            with conn:
                try:
                    data = conn.recv(65536)
                except Exception:
                    continue

            if not data:
                continue

            for raw_line in data.decode("utf-8", errors="replace").splitlines():
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    payload = json.loads(raw_line)
                except Exception as exc:
                    log.warning("GuiSupervisor failed to parse heartbeat payload: %s", exc)
                    continue
                if isinstance(payload, dict):
                    self.registry.apply_message(payload)


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


def _spawn_window_process(
    *,
    mode: str,
    window_kind: str,
    backend_socket: str,
    supervisor_socket: str,
    selected_test: str | None = None,
    start_run_payload: dict[str, Any] | None = None,
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
        supervisor_socket,
    ]

    if selected_test:
        cmd.extend(["--selected-test", selected_test])

    if start_run_payload:
        raw = json.dumps(start_run_payload, ensure_ascii=False, sort_keys=False).encode("utf-8")
        encoded = base64.urlsafe_b64encode(raw).decode("ascii")
        cmd.extend(["--start-run-payload-b64", encoded])

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    process = subprocess.Popen(
        cmd,
        cwd=str(_project_root()),
        env=env,
        text=True,
        start_new_session=False,
    )
    log.info("GuiSupervisor spawned %s %s window pid=%s", mode, window_kind, process.pid)
    return process


def _monitor_session(
    *,
    mode: str,
    backend_socket: str,
    supervisor_socket: str,
    selected_test: str | None,
    start_run_payload: dict[str, Any] | None,
    child_map: dict[str, subprocess.Popen[str]],
    registry: HeartbeatRegistry,
) -> int:
    stale_log_times: dict[str, float] = {}
    respawn_times: dict[str, list[float]] = {
        "controller": [],
        "scada": [],
    }
    last_recording_state: bool = (mode == "live")
    last_backend_poll_monotonic = 0.0
    initial_start_run_consumed = False

    def refresh_recording_state(force: bool = False) -> bool:
        nonlocal last_recording_state, last_backend_poll_monotonic
        now = time.monotonic()
        if not force and now - last_backend_poll_monotonic < _BACKEND_STATE_POLL_S:
            return last_recording_state

        snapshot = _request_backend_state_snapshot(backend_socket)
        extracted = _extract_recording_active_from_snapshot(snapshot)
        if extracted is not None:
            if extracted != last_recording_state:
                log.info(
                    "GuiSupervisor recording_active changed: %s -> %s",
                    last_recording_state,
                    extracted,
                )
            last_recording_state = extracted
        last_backend_poll_monotonic = now
        return last_recording_state

    def respawn_window(window_kind: str, *, reason: str) -> bool:
        nonlocal initial_start_run_consumed
        now = time.monotonic()
        respawn_times[window_kind] = _prune_respawn_times(respawn_times[window_kind], now=now)
        if len(respawn_times[window_kind]) >= _RESPAWN_LIMIT_COUNT:
            log.error(
                "GuiSupervisor refusing to respawn %s window; respawn limit exceeded in %.0fs window",
                window_kind,
                _RESPAWN_LIMIT_WINDOW_S,
            )
            return False

        window_role = _window_role_for(mode, window_kind)
        registry.forget_role(window_role)

        payload_for_spawn = None
        if mode == "live" and window_kind == "controller" and not initial_start_run_consumed:
            payload_for_spawn = start_run_payload
            initial_start_run_consumed = True

        process = _spawn_window_for_role(
            mode=mode,
            window_kind=window_kind,
            backend_socket=backend_socket,
            supervisor_socket=supervisor_socket,
            selected_test=selected_test,
            start_run_payload=payload_for_spawn,
        )
        child_map[window_kind] = process
        respawn_times[window_kind].append(now)
        log.warning(
            "GuiSupervisor respawned %s window pid=%s because %s",
            window_kind,
            process.pid,
            reason,
        )
        return True

    try:
        # Mark the start_run payload as already consumed once the initial live controller
        # window has been launched from main().
        if mode == "live":
            initial_start_run_consumed = True

        while True:
            recording_active = refresh_recording_state()

            exited_name = None
            exited_code = None

            for name, process in child_map.items():
                return_code = process.poll()
                if return_code is not None:
                    exited_name = name
                    exited_code = return_code
                    break

            if exited_name is not None:
                if _window_respawn_allowed(mode=mode, recording_active=recording_active):
                    log.warning(
                        "%s window exited with code=%s while recording is active; respawning",
                        exited_name,
                        exited_code,
                    )
                    if not respawn_window(exited_name, reason=f"exit code {exited_code}"):
                        log.error(
                            "GuiSupervisor falling back to full session shutdown because %s could not be respawned",
                            exited_name,
                        )
                        for name, process in child_map.items():
                            if name == exited_name:
                                continue
                            _terminate_process(process, label=f"{name} window")
                            _wait_for_process_exit(process, timeout_s=2.0)
                            if process.poll() is None:
                                _kill_process(process, label=f"{name} window")
                                _wait_for_process_exit(process, timeout_s=1.0)
                        return int(exited_code or 1)
                    time.sleep(_MONITOR_POLL_S)
                    continue

                log.info(
                    "%s window exited with code=%s; shutting down remaining GUI windows for this %s session",
                    exited_name,
                    exited_code,
                    mode,
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

            now = time.monotonic()
            for record in registry.snapshot():
                window_role = str(record.get("window_role") or "")
                window_kind = str(record.get("window_kind") or "")
                last_monotonic = record.get("last_monotonic")
                if not window_role or not window_kind or not isinstance(last_monotonic, (int, float)):
                    continue

                age = now - float(last_monotonic)
                if age >= _HEARTBEAT_STALE_AFTER_S:
                    previous_log_time = stale_log_times.get(window_role, 0.0)
                    if now - previous_log_time >= _HEARTBEAT_STALE_AFTER_S:
                        stale_log_times[window_role] = now
                        log.warning(
                            "GuiSupervisor heartbeat stale for %s: age=%.2fs pid=%s session=%s",
                            window_role,
                            age,
                            record.get("pid"),
                            record.get("session_id"),
                        )

                    if _window_respawn_allowed(mode=mode, recording_active=recording_active):
                        process = child_map.get(window_kind)
                        if process is None:
                            continue

                        log.warning(
                            "GuiSupervisor terminating stale %s window pid=%s so it can be respawned",
                            window_kind,
                            process.pid,
                        )
                        _terminate_process(process, label=f"{window_kind} window")
                        _wait_for_process_exit(process, timeout_s=_RESPAWN_KILL_TIMEOUT_S)
                        if process.poll() is None:
                            _kill_process(process, label=f"{window_kind} window")
                            _wait_for_process_exit(process, timeout_s=1.0)

                        if not respawn_window(window_kind, reason=f"stale heartbeat age={age:.2f}s"):
                            log.error(
                                "GuiSupervisor could not respawn stale %s window; shutting down session",
                                window_kind,
                            )
                            for name, other_process in child_map.items():
                                if name == window_kind:
                                    continue
                                _terminate_process(other_process, label=f"{name} window")
                                _wait_for_process_exit(other_process, timeout_s=2.0)
                                if other_process.poll() is None:
                                    _kill_process(other_process, label=f"{name} window")
                                    _wait_for_process_exit(other_process, timeout_s=1.0)
                            return 1
                        break

            time.sleep(_MONITOR_POLL_S)
    except KeyboardInterrupt:
        log.info("GuiSupervisor interrupted; terminating child GUI windows")
        for name, process in child_map.items():
            _terminate_process(process, label=f"{name} window")
        for process in child_map.values():
            _wait_for_process_exit(process, timeout_s=2.0)
        for name, process in child_map.items():
            if process.poll() is None:
                _kill_process(process, label=f"{name} window")
        return 130


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
            if lowered in {"idle", "completed", "stopped", "not_running"}:
                return False

        current_run_id = run_section.get("run_id")
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


def _spawn_window_for_role(
    *,
    mode: str,
    window_kind: str,
    backend_socket: str,
    supervisor_socket: str,
    selected_test: str | None,
    start_run_payload: dict[str, Any] | None,
) -> subprocess.Popen[str]:
    return _spawn_window_process(
        mode=mode,
        window_kind=window_kind,
        backend_socket=backend_socket,
        supervisor_socket=supervisor_socket,
        selected_test=selected_test,
        start_run_payload=start_run_payload,
    )


def _window_role_for(mode: str, window_kind: str) -> str:
    return f"{mode}_{window_kind}"


def _window_respawn_allowed(
    *,
    mode: str,
    recording_active: bool,
) -> bool:
    return mode == "live" and recording_active


def _prune_respawn_times(respawn_times: list[float], *, now: float) -> list[float]:
    return [value for value in respawn_times if now - value <= _RESPAWN_LIMIT_WINDOW_S]


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch and monitor split minTS GUI windows")
    parser.add_argument("--mode", choices=("live", "playback"), required=True)
    parser.add_argument("--backend-socket", required=True)
    parser.add_argument("--selected-test")
    parser.add_argument("--start-run-payload-b64")
    return parser


def main() -> int:
    _configure_logging()
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.mode == "playback" and not args.selected_test:
        parser.error("--selected-test is required for playback mode")

    registry = HeartbeatRegistry()
    socket_dir = Path(tempfile.gettempdir()) / "mints_scada_supervisor"
    socket_dir.mkdir(parents=True, exist_ok=True)
    supervisor_socket_path = socket_dir / f"gui_supervisor_{os.getpid()}.sock"
    heartbeat_server = HeartbeatServer(socket_path=supervisor_socket_path, registry=registry)
    heartbeat_server.start()

    processes: dict[str, subprocess.Popen[str]] = {}
    try:
        processes["controller"] = _spawn_window_process(
            mode=args.mode,
            window_kind="controller",
            backend_socket=args.backend_socket,
            supervisor_socket=str(supervisor_socket_path),
            selected_test=args.selected_test,
            start_run_payload=_decode_json_arg(args.start_run_payload_b64) if args.mode == "live" else None,
        )
        processes["scada"] = _spawn_window_process(
            mode=args.mode,
            window_kind="scada",
            backend_socket=args.backend_socket,
            supervisor_socket=str(supervisor_socket_path),
            selected_test=args.selected_test,
            start_run_payload=None,
        )

        return _monitor_session(
            mode=args.mode,
            backend_socket=args.backend_socket,
            supervisor_socket=str(supervisor_socket_path),
            selected_test=args.selected_test,
            start_run_payload=_decode_json_arg(args.start_run_payload_b64) if args.mode == "live" else None,
            child_map=processes,
            registry=registry,
        )
    finally:
        heartbeat_server.stop()
        for name, process in processes.items():
            if process.poll() is None:
                _terminate_process(process, label=f"{name} window")
                _wait_for_process_exit(process, timeout_s=1.0)
                if process.poll() is None:
                    _kill_process(process, label=f"{name} window")


if __name__ == "__main__":
    sys.exit(main())
