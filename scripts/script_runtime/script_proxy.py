from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Mapping

from scripts.script_runtime.script_protocol import (
    SCRIPT_HOST_MESSAGE_HOST_READY,
    SCRIPT_HOST_MESSAGE_PING,
    SCRIPT_HOST_MESSAGE_PONG,
    SCRIPT_HOST_MESSAGE_SHUTDOWN,
    SCRIPT_HOST_MESSAGE_SHUTDOWN_ACK,
    build_message,
    decode_json_line,
    encode_json_line,
)


class ScriptHostProxy:
    """Backend-side process wrapper for the future subprocess script host.

    Commit4 scope: launch the host scaffold, exchange protocol messages, and own
    shutdown/termination. Production script execution will flip over in commit5.
    """

    def __init__(
        self,
        *,
        project_root: str | Path,
        python_executable: str | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.python_executable = python_executable or sys.executable
        self._process: subprocess.Popen[str] | None = None
        self._stdout_thread: threading.Thread | None = None
        self._message_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._stderr_thread: threading.Thread | None = None

    @property
    def process(self) -> subprocess.Popen[str] | None:
        return self._process

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, *, script_path: str | None = None, cwd: str | None = None) -> dict[str, Any]:
        if self.is_running:
            raise RuntimeError("ScriptHostProxy.start() called while host is already running")

        host_path = self.project_root / "scripts" / "script_runtime" / "script_host.py"
        command = [self.python_executable, "-u", str(host_path)]
        if script_path:
            command.extend(["--script-path", script_path])
        if cwd:
            command.extend(["--cwd", cwd])

        env = os.environ.copy()
        pythonpath_parts = [str(self.project_root)]
        if env.get("PYTHONPATH"):
            pythonpath_parts.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)

        self._process = subprocess.Popen(
            command,
            cwd=str(self.project_root),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._stdout_thread = threading.Thread(target=self._pump_stdout, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread = threading.Thread(target=self._pump_stderr, daemon=True)
        self._stderr_thread.start()

        ready = self.read_message(expected_type=SCRIPT_HOST_MESSAGE_HOST_READY, timeout_s=3.0)
        return ready

    def send_request(
        self,
        message_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout_s: float = 3.0,
        expected_type: str | None = None,
    ) -> dict[str, Any]:
        if not self.is_running or self._process is None or self._process.stdin is None:
            raise RuntimeError("Script host is not running")
        request_id = uuid.uuid4().hex
        self._process.stdin.write(
            encode_json_line(build_message(message_type, payload, request_id=request_id)).decode("utf-8")
        )
        self._process.stdin.flush()
        if expected_type is None:
            return {"ok": True, "request_id": request_id}
        response = self.read_message(expected_type=expected_type, timeout_s=timeout_s)
        if response.get("request_id") != request_id:
            raise RuntimeError(
                f"Script host response request_id {response.get('request_id')!r} did not match {request_id!r}"
            )
        return response

    def ping(self, *, timeout_s: float = 3.0) -> dict[str, Any]:
        return self.send_request(
            SCRIPT_HOST_MESSAGE_PING,
            {"ok": True},
            timeout_s=timeout_s,
            expected_type=SCRIPT_HOST_MESSAGE_PONG,
        )

    def shutdown(self, *, timeout_s: float = 3.0) -> dict[str, Any]:
        response = self.send_request(
            SCRIPT_HOST_MESSAGE_SHUTDOWN,
            {"reason": "proxy_shutdown"},
            timeout_s=timeout_s,
            expected_type=SCRIPT_HOST_MESSAGE_SHUTDOWN_ACK,
        )
        self.wait(timeout_s=timeout_s)
        self.close()
        return response

    def wait(self, *, timeout_s: float = 3.0) -> int | None:
        if self._process is None:
            return None
        return self._process.wait(timeout=timeout_s)

    def terminate(self) -> int | None:
        if self._process is None:
            return None
        if self._process.poll() is None:
            self._process.terminate()
        return_code = self._process.wait(timeout=3.0)
        self.close()
        return return_code

    def close(self) -> None:
        if self._process is None:
            return
        for stream_name in ("stdin", "stdout", "stderr"):
            stream = getattr(self._process, stream_name)
            if stream is None:
                continue
            try:
                stream.close()
            except Exception:
                pass
        self._process = None

    def read_message(self, *, expected_type: str, timeout_s: float) -> dict[str, Any]:
        deadline = threading.Event()
        del deadline
        while True:
            try:
                message = self._message_queue.get(timeout=timeout_s)
            except queue.Empty as exc:
                raise TimeoutError(
                    f"Timed out waiting for script host message type {expected_type!r}"
                ) from exc
            if message.get("type") == expected_type:
                return message

    def _pump_stdout(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        for line in self._process.stdout:
            stripped = line.strip()
            if not stripped:
                continue
            decoded = decode_json_line(stripped)
            self._message_queue.put(decoded)

    def _pump_stderr(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        for line in self._process.stderr:
            self._stderr_lines.append(line.rstrip("\n"))
