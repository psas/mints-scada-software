from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass
class ScriptStartResult:
    script_id: str
    name: str
    pid: int
    launch_mode: str
    command: list[str]
    cwd: str | None


class ScriptRunner:
    """Backend-owned subprocess script runner skeleton.

    Supported start payload shapes:
    - {"name": "...", "command": ["python3", "script.py", ...], "cwd": "...", "env": {...}}
    - {"name": "...", "inline_python": "print('hello')", "cwd": "...", "env": {...}}

    Current scope:
    - single running script at a time
    - subprocess lifecycle ownership in backend
    - polling thread to detect exit
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._script_id: str | None = None
        self._script_name: str | None = None
        self._launch_mode: str | None = None
        self._command: list[str] = []
        self._cwd: str | None = None
        self._watcher_thread: threading.Thread | None = None
        self._stop_watcher = threading.Event()
        self._on_exit = None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def start_script(
        self,
        payload: Mapping[str, Any],
        *,
        script_id: str,
        on_exit,
    ) -> ScriptStartResult:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise RuntimeError("A backend-owned script is already running")

            name = self._require_non_empty_string(payload, "name")
            cwd = self._get_optional_string(payload, "cwd")
            env_overrides = self._get_optional_string_mapping(payload, "env") or {}

            command = self._build_command(payload)
            if not command:
                raise ValueError("Script start payload must define either 'command' or 'inline_python'")

            merged_env = os.environ.copy()
            merged_env.update(env_overrides)

            process = subprocess.Popen(
                command,
                cwd=cwd or None,
                env=merged_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )

            self._process = process
            self._script_id = script_id
            self._script_name = name
            self._launch_mode = "inline_python" if "inline_python" in payload else "command"
            self._command = list(command)
            self._cwd = cwd
            self._on_exit = on_exit

            self._stop_watcher.clear()
            self._watcher_thread = threading.Thread(
                target=self._watch_process,
                name=f"backend-script-watcher-{script_id[:8]}",
                daemon=True,
            )
            self._watcher_thread.start()

            return ScriptStartResult(
                script_id=script_id,
                name=name,
                pid=process.pid,
                launch_mode=self._launch_mode,
                command=list(command),
                cwd=cwd,
            )

    def stop_script(self, *, reason: str = "operator_stop", timeout_s: float = 3.0) -> dict[str, Any]:
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                raise RuntimeError("No running backend-owned script to stop")

            process = self._process
            script_id = self._script_id
            script_name = self._script_name
            pid = process.pid

        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

        try:
            return_code = process.wait(timeout=timeout_s)
            stopped_via = "sigterm"
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return_code = process.wait(timeout=1.0)
            stopped_via = "sigkill"

        self._stop_watcher.set()
        self._clear_after_exit()

        return {
            "script_id": script_id,
            "name": script_name,
            "pid": pid,
            "reason": reason,
            "returncode": return_code,
            "stopped_via": stopped_via,
        }

    def shutdown(self) -> None:
        with self._lock:
            running = self._process is not None and self._process.poll() is None
        if running:
            try:
                self.stop_script(reason="backend_shutdown")
            except Exception:
                pass

    def _watch_process(self) -> None:
        with self._lock:
            process = self._process
            script_id = self._script_id
            script_name = self._script_name
            launch_mode = self._launch_mode
            command = list(self._command)
            cwd = self._cwd
            on_exit = self._on_exit

        if process is None:
            return

        return_code = process.wait()

        if self._stop_watcher.is_set():
            return

        self._clear_after_exit()

        if callable(on_exit):
            on_exit(
                {
                    "script_id": script_id,
                    "name": script_name,
                    "pid": process.pid,
                    "launch_mode": launch_mode,
                    "command": command,
                    "cwd": cwd,
                    "returncode": return_code,
                }
            )

    def _clear_after_exit(self) -> None:
        with self._lock:
            self._process = None
            self._script_id = None
            self._script_name = None
            self._launch_mode = None
            self._command = []
            self._cwd = None
            self._on_exit = None

    def _build_command(self, payload: Mapping[str, Any]) -> list[str]:
        if "command" in payload:
            value = payload["command"]
            if not isinstance(value, list) or not value:
                raise ValueError("'command' must be a non-empty list of strings")
            command: list[str] = []
            for item in value:
                if not isinstance(item, str) or not item.strip():
                    raise ValueError("'command' list entries must be non-empty strings")
                command.append(item)
            return command

        if "inline_python" in payload:
            code = payload["inline_python"]
            if not isinstance(code, str) or not code.strip():
                raise ValueError("'inline_python' must be a non-empty string")
            return [sys.executable, "-c", code]

        return []

    def _require_non_empty_string(self, payload: Mapping[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Script payload must include a non-empty string '{key}'")
        return value.strip()

    def _get_optional_string(self, payload: Mapping[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"Script payload field '{key}' must be a string when provided")
        stripped = value.strip()
        return stripped or None

    def _get_optional_string_mapping(
        self,
        payload: Mapping[str, Any],
        key: str,
    ) -> dict[str, str] | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError(f"Script payload field '{key}' must be an object when provided")

        result: dict[str, str] = {}
        for env_key, env_value in value.items():
            if not isinstance(env_key, str):
                raise ValueError(f"Script env key {env_key!r} must be a string")
            if not isinstance(env_value, str):
                raise ValueError(f"Script env value for {env_key!r} must be a string")
            result[env_key] = env_value
        return result
