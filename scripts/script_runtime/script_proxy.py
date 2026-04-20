"""scripts/script_runtime/script_proxy.py

Backend-side proxy for the isolated legacy script host subprocess.

This module manages the backend-owned subprocess that runs ``script_host.py``.
It starts the host with the project root on ``PYTHONPATH``, exchanges JSONL
protocol messages over stdio, matches replies by message type and request ID,
and captures host stderr output for diagnostics.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Mapping

from scripts.script_runtime.script_protocol import (
    SCRIPT_HOST_MESSAGE_EXECUTE_LEGACY_SCRIPT,
    SCRIPT_HOST_MESSAGE_EXECUTE_STARTED,
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
    """Wrap the subprocess-backed legacy script host used by the backend.

    The proxy owns host process startup, request/response exchange over stdio,
    asynchronous stdout and stderr pumping, and request matching for protocol
    messages that carry a response type and request ID.
    """

    def __init__(
        self,
        *,
        project_root: str | Path,
        python_executable: str | None = None,
    ) -> None:
        """Initialize the subprocess proxy.

        Args:
            project_root: Repository root used to resolve ``script_host.py`` and
                seed ``PYTHONPATH`` for the child process.
            python_executable: Python interpreter used to launch the host. When
                omitted, the current interpreter is reused.
        """
        self.project_root = Path(project_root).expanduser().resolve()
        self.python_executable = python_executable or sys.executable
        self._process: subprocess.Popen[str] | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._message_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._pending_messages: deque[dict[str, Any]] = deque()
        self._stderr_lines: list[str] = []

    @property
    def process(self) -> subprocess.Popen[str] | None:
        """Return the active host process handle.

        Returns:
            The running or exited subprocess handle, or None when the host has
            not been started or has already been fully closed.
        """
        return self._process

    @property
    def is_running(self) -> bool:
        """Return whether the host process is currently alive.

        Returns:
            True when a subprocess handle exists and has not exited yet.
        """
        return self._process is not None and self._process.poll() is None

    @property
    def stderr_lines(self) -> list[str]:
        """Return a snapshot of captured host stderr lines.

        Returns:
            A copy of the stderr lines collected by the background stderr pump.
        """
        return list(self._stderr_lines)

    def start(
        self, *, script_path: str | None = None, cwd: str | None = None
    ) -> dict[str, Any]:
        """Start the script host subprocess and wait for the ready message.

        Args:
            script_path: Optional script path forwarded to ``script_host.py``.
            cwd: Optional working directory argument forwarded to the host.

        Returns:
            The decoded ``host_ready`` protocol message emitted by the child
            process after startup completes.

        Raises:
            RuntimeError: The host is already running.
            TimeoutError: The host does not emit ``host_ready`` before the
                startup timeout expires.
            OSError: Launching the child process fails.
        """
        if self.is_running:
            raise RuntimeError(
                "ScriptHostProxy.start() called while host is already running"
            )

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
            start_new_session=True,
        )
        self._stdout_thread = threading.Thread(target=self._pump_stdout, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread = threading.Thread(target=self._pump_stderr, daemon=True)
        self._stderr_thread.start()

        return self._read_matching_message(
            expected_type=SCRIPT_HOST_MESSAGE_HOST_READY,
            request_id=None,
            timeout_s=3.0,
        )

    def send_request(
        self,
        message_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout_s: float = 3.0,
        expected_type: str | None = None,
    ) -> dict[str, Any]:
        """Send one protocol request to the host and optionally await a reply.

        Args:
            message_type: Protocol message type to send.
            payload: Message payload mapping to encode.
            timeout_s: Maximum time to wait for the expected response when one
                is required.
            expected_type: Response message type to wait for. When omitted, the
                call returns immediately after writing the request.

        Returns:
            A small acknowledgement containing the generated request ID when no
            response type is requested. Otherwise, the decoded matching host
            response.

        Raises:
            RuntimeError: The host is not running or stdin is unavailable.
            TimeoutError: The expected response does not arrive before the
                timeout expires.
        """
        if not self.is_running or self._process is None or self._process.stdin is None:
            raise RuntimeError("Script host is not running")

        request_id = uuid.uuid4().hex
        request_bytes = encode_json_line(
            build_message(message_type, payload, request_id=request_id)
        )
        self._process.stdin.write(request_bytes.decode("utf-8"))
        self._process.stdin.flush()
        if expected_type is None:
            return {"ok": True, "request_id": request_id}
        return self._read_matching_message(
            expected_type=expected_type,
            request_id=request_id,
            timeout_s=timeout_s,
        )

    def execute_legacy_script(
        self,
        *,
        script_text: str,
        device_ids: list[str],
        timeout_s: float = 3.0,
    ) -> dict[str, Any]:
        """Request execution of a legacy script through the host.

        Args:
            script_text: Legacy script source code to execute.
            device_ids: Device IDs exposed to the legacy script environment.
            timeout_s: Maximum time to wait for the host to acknowledge start.

        Returns:
            The decoded ``execute_started`` message returned by the host.

        Raises:
            RuntimeError: The host is not running.
            TimeoutError: The host does not acknowledge script start before the
                timeout expires.
        """
        return self.send_request(
            SCRIPT_HOST_MESSAGE_EXECUTE_LEGACY_SCRIPT,
            {
                "script_text": script_text,
                "device_ids": list(device_ids),
            },
            timeout_s=timeout_s,
            expected_type=SCRIPT_HOST_MESSAGE_EXECUTE_STARTED,
        )

    def ping(self, *, timeout_s: float = 3.0) -> dict[str, Any]:
        """Round-trip a ping request through the host protocol.

        Args:
            timeout_s: Maximum time to wait for the pong response.

        Returns:
            The decoded ``pong`` response message.

        Raises:
            RuntimeError: The host is not running.
            TimeoutError: The host does not respond before the timeout expires.
        """
        return self.send_request(
            SCRIPT_HOST_MESSAGE_PING,
            {"ok": True},
            timeout_s=timeout_s,
            expected_type=SCRIPT_HOST_MESSAGE_PONG,
        )

    def shutdown(self, *, timeout_s: float = 3.0) -> dict[str, Any]:
        """Request graceful host shutdown and close local process resources.

        Args:
            timeout_s: Maximum time to wait for the shutdown acknowledgement and
                process exit.

        Returns:
            The decoded ``shutdown_ack`` response message.

        Raises:
            RuntimeError: The host is not running.
            TimeoutError: The acknowledgement or process exit does not complete
                before the timeout expires.
        """
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
        """Wait for the host process to exit.

        Args:
            timeout_s: Maximum time to wait for process termination.

        Returns:
            The child process return code, or None when no process has been
            started.

        Raises:
            subprocess.TimeoutExpired: The process does not exit before the
                timeout expires.
        """
        if self._process is None:
            return None
        return self._process.wait(timeout=timeout_s)

    def terminate(self) -> int | None:
        """Terminate the host process and close local resources.

        Returns:
            The child process return code, or None when no process has been
            started.

        Raises:
            subprocess.TimeoutExpired: The process does not exit within the
                fixed termination wait window.
        """
        if self._process is None:
            return None
        if self._process.poll() is None:
            self._process.terminate()
        return_code = self._process.wait(timeout=3.0)
        self.close()
        return return_code

    def close(self) -> None:
        """Close stdio streams and clear the stored subprocess handle.

        This only releases local resources. It does not first request child
        shutdown or verify that the child has exited.

        Returns:
            None.
        """
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

    def read_next_message(self, *, timeout_s: float = 0.5) -> dict[str, Any]:
        """Read the next available host message from pending or queued data.

        Args:
            timeout_s: Maximum time to wait for a queued message when no
                deferred message is already pending.

        Returns:
            The next decoded host message.

        Raises:
            TimeoutError: No message becomes available before the timeout
                expires.
        """
        if self._pending_messages:
            return self._pending_messages.popleft()
        try:
            return self._message_queue.get(timeout=timeout_s)
        except queue.Empty as exc:
            raise TimeoutError(
                "Timed out waiting for next script host message"
            ) from exc

    def _read_matching_message(
        self,
        *,
        expected_type: str,
        request_id: str | None,
        timeout_s: float,
    ) -> dict[str, Any]:
        """Read the next message matching a response type and optional request ID.

        Non-matching messages are deferred into the pending-message deque and
        restored in original order before returning or timing out.

        Args:
            expected_type: Protocol message type to wait for.
            request_id: Optional request ID that must also match.
            timeout_s: Maximum time to wait for a matching message.

        Returns:
            The decoded matching protocol message.

        Raises:
            TimeoutError: A matching message is not observed before the timeout
                expires.
        """
        deadline = time.monotonic() + timeout_s
        deferred: deque[dict[str, Any]] = deque()
        while True:
            while self._pending_messages:
                message = self._pending_messages.popleft()
                if message.get("type") == expected_type and (
                    request_id is None or message.get("request_id") == request_id
                ):
                    while deferred:
                        self._pending_messages.appendleft(deferred.pop())
                    return message
                deferred.append(message)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                while deferred:
                    self._pending_messages.appendleft(deferred.pop())
                raise TimeoutError(
                    f"Timed out waiting for script host message type {expected_type!r}"
                )

            try:
                message = self._message_queue.get(timeout=remaining)
            except queue.Empty as exc:
                while deferred:
                    self._pending_messages.appendleft(deferred.pop())
                raise TimeoutError(
                    f"Timed out waiting for script host message type {expected_type!r}"
                ) from exc

            if message.get("type") == expected_type and (
                request_id is None or message.get("request_id") == request_id
            ):
                while deferred:
                    self._pending_messages.appendleft(deferred.pop())
                return message
            deferred.append(message)

    def _pump_stdout(self) -> None:
        """Decode host stdout JSONL messages into the inbound message queue.

        Returns:
            None.
        """
        assert self._process is not None and self._process.stdout is not None
        for line in self._process.stdout:
            stripped = line.strip()
            if not stripped:
                continue
            decoded = decode_json_line(stripped)
            self._message_queue.put(decoded)

    def _pump_stderr(self) -> None:
        """Collect raw stderr lines from the host for later diagnostics.

        Returns:
            None.
        """
        assert self._process is not None and self._process.stderr is not None
        for line in self._process.stderr:
            self._stderr_lines.append(line.rstrip("\n"))
