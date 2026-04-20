"""scripts/script_runtime/script_host.py

Subprocess stdio host for legacy minTS script execution.

This module runs a JSONL-based script host process that executes legacy script
text inside an isolated runtime facade. The host exposes a small request/response
protocol over stdin/stdout so a parent process can start a script, receive
script output, and translate script-issued abort and command requests into
structured host messages.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from scripts.script_runtime.script_contract import describe_legacy_script_contract
except ModuleNotFoundError:  # pragma: no cover - fallback for isolated scaffold testing

    def describe_legacy_script_contract() -> dict[str, object]:
        """Return a minimal legacy contract description for scaffold-only runs.

        Returns:
            A fallback description of the supported legacy script surface and
            deprecated members when the full script contract module is not
            importable.
        """
        return {
            "supported_surface": ["print", "wait", "abort", "mints.devices"],
            "deprecated_mints_members": ["graph", "exporter", "autopoller"],
        }


from scripts.script_runtime.script_compat import (
    LegacyScriptRuntimeFacade,
    ScriptHostCallbacks,
    default_wait_callback,
)
from scripts.script_runtime.script_protocol import (
    SCRIPT_HOST_MESSAGE_ABORT_REQUEST,
    SCRIPT_HOST_MESSAGE_COMMAND_REQUEST,
    SCRIPT_HOST_MESSAGE_ERROR,
    SCRIPT_HOST_MESSAGE_EXECUTE_LEGACY_SCRIPT,
    SCRIPT_HOST_MESSAGE_EXECUTE_STARTED,
    SCRIPT_HOST_MESSAGE_HOST_READY,
    SCRIPT_HOST_MESSAGE_PING,
    SCRIPT_HOST_MESSAGE_PONG,
    SCRIPT_HOST_MESSAGE_SCRIPT_EXIT,
    SCRIPT_HOST_MESSAGE_SCRIPT_OUTPUT,
    SCRIPT_HOST_MESSAGE_SHUTDOWN,
    SCRIPT_HOST_MESSAGE_SHUTDOWN_ACK,
    SCRIPT_HOST_SUPPORTED_REQUEST_TYPES,
    build_message,
    decode_json_line,
    encode_json_line,
)


def isoformat_z() -> str:
    """Return the current UTC time in millisecond-resolution ISO-8601 form.

    Returns:
        Current UTC wall time formatted as ``YYYY-MM-DDTHH:MM:SS.mmmZ``.
    """
    return (
        time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        + f".{int((time.time() % 1) * 1000):03d}Z"
    )


class ScriptHostServer:
    """Run the legacy script host protocol over stdio.

    The host accepts JSONL requests from stdin, emits protocol messages to
    stdout, and executes at most one legacy script at a time in a background
    thread. Script-visible functions such as ``print``, ``wait``, ``abort``,
    and ``mints`` are provided by ``LegacyScriptRuntimeFacade`` and bridged
    back to the parent process through protocol messages.
    """

    def __init__(
        self, *, script_path: str | None = None, cwd: str | None = None
    ) -> None:
        """Initialize host process state for a future script execution session.

        Args:
            script_path: Source script path to report in host protocol metadata.
            cwd: Working directory to report in host protocol metadata.
        """
        self.script_path = script_path
        self.cwd = cwd
        self._running = True
        self._script_thread: threading.Thread | None = None
        self._script_lock = threading.RLock()
        self._active_request_id: str | None = None

    def emit(self, payload: Mapping[str, Any]) -> None:
        """Write one protocol message to stdout as a JSONL record.

        Args:
            payload: Protocol payload to encode and emit.

        Returns:
            None.
        """
        sys.stdout.buffer.write(encode_json_line(payload))
        sys.stdout.buffer.flush()

    def emit_ready(self) -> None:
        """Publish the initial host-ready handshake message.

        The emitted payload describes the host process, the supported request
        types, the exposed legacy script contract, and the host start time.

        Returns:
            None.
        """
        self.emit(
            build_message(
                SCRIPT_HOST_MESSAGE_HOST_READY,
                {
                    "pid": os.getpid(),
                    "cwd": self.cwd,
                    "script_path": self.script_path,
                    "supported_requests": list(SCRIPT_HOST_SUPPORTED_REQUEST_TYPES),
                    "legacy_contract": describe_legacy_script_contract(),
                    "started_at": isoformat_z(),
                },
            )
        )

    def serve_forever(self) -> int:
        """Run the stdio request loop until shutdown or stdin closes.

        The loop emits the initial ready message, decodes newline-delimited JSON
        requests from stdin, dispatches them to the host request handler, and
        converts unexpected exceptions into protocol error messages.

        Returns:
            Exit status for the host process.
        """
        self.emit_ready()
        while self._running:
            line = sys.stdin.readline()
            if line == "":
                break
            stripped = line.strip()
            if not stripped:
                continue
            try:
                request = decode_json_line(stripped)
                response = self._handle_request(request)
            except Exception as exc:
                response = build_message(
                    SCRIPT_HOST_MESSAGE_ERROR,
                    {
                        "message": str(exc),
                        "host_pid": os.getpid(),
                    },
                )
            if response is not None:
                self.emit(response)
        return 0

    def _handle_request(self, request: Mapping[str, Any]) -> dict[str, Any] | None:
        """Handle a single decoded host request.

        Supported requests are ping, shutdown, and legacy-script execution.
        Unsupported request types or invalid payload shapes raise protocol
        errors that are converted to error messages by ``serve_forever``.

        Args:
            request: Decoded protocol request mapping.

        Returns:
            A protocol response payload to emit immediately, or None when the
            request only produces asynchronous follow-up messages.

        Raises:
            ValueError: If the payload is not an object or the request type is
                unsupported.
        """
        request_type = str(request.get("type"))
        request_id = request.get("request_id")
        payload = request.get("payload")
        if payload is None:
            payload = {}
        if not isinstance(payload, Mapping):
            raise ValueError("Script host request payload must be an object")

        if request_type == SCRIPT_HOST_MESSAGE_PING:
            return build_message(
                SCRIPT_HOST_MESSAGE_PONG,
                {
                    "ok": True,
                    "host_pid": os.getpid(),
                    "script_path": self.script_path,
                    "wall_time": isoformat_z(),
                },
                request_id=request_id if isinstance(request_id, str) else None,
            )

        if request_type == SCRIPT_HOST_MESSAGE_SHUTDOWN:
            self._running = False
            return build_message(
                SCRIPT_HOST_MESSAGE_SHUTDOWN_ACK,
                {
                    "ok": True,
                    "host_pid": os.getpid(),
                    "wall_time": isoformat_z(),
                },
                request_id=request_id if isinstance(request_id, str) else None,
            )

        if request_type == SCRIPT_HOST_MESSAGE_EXECUTE_LEGACY_SCRIPT:
            return self._handle_execute_legacy_script(payload, request_id)

        raise ValueError(f"Unsupported script host request type: {request_type!r}")

    def _handle_execute_legacy_script(
        self,
        payload: Mapping[str, Any],
        request_id: Any,
    ) -> dict[str, Any]:
        """Start executing one legacy script in the background.

        The host validates the request, ensures no other legacy script is
        currently running in this process, records the active request id, and
        starts a daemon thread that executes the provided script text.

        Args:
            payload: Execute request payload containing script text and optional
                device ids.
            request_id: Protocol request identifier associated with the run.

        Returns:
            The immediate ``execute_started`` protocol response.

        Raises:
            ValueError: If the request id, script text, or device id list is
                missing or malformed.
            RuntimeError: If another legacy script is already active in this
                host process.
        """
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError(
                "execute_legacy_script requires a non-empty string request_id"
            )

        with self._script_lock:
            if self._script_thread is not None and self._script_thread.is_alive():
                raise RuntimeError("A legacy script is already running in this host")

            script_text = payload.get("script_text")
            if not isinstance(script_text, str) or not script_text.strip():
                raise ValueError(
                    "execute_legacy_script requires a non-empty 'script_text'"
                )

            device_ids_value = payload.get("device_ids") or []
            if not isinstance(device_ids_value, list):
                raise ValueError(
                    "execute_legacy_script field 'device_ids' must be a list when provided"
                )
            device_ids = [str(item) for item in device_ids_value]

            self._active_request_id = request_id
            self._script_thread = threading.Thread(
                target=self._run_legacy_script,
                args=(script_text, device_ids, request_id),
                name=f"script-host-{request_id[:8]}",
                daemon=True,
            )
            self._script_thread.start()

        return build_message(
            SCRIPT_HOST_MESSAGE_EXECUTE_STARTED,
            {
                "ok": True,
                "host_pid": os.getpid(),
                "script_path": self.script_path,
                "device_count": len(device_ids),
                "started_at": isoformat_z(),
            },
            request_id=request_id,
        )

    def _run_legacy_script(
        self, script_text: str, device_ids: list[str], request_id: str
    ) -> None:
        """Execute legacy script text inside the compatibility facade.

        The script runs with a restricted globals dictionary backed by
        ``LegacyScriptRuntimeFacade``. Script prints, waits, aborts, and device
        commands are converted into host protocol messages through callback
        hooks. Completion always emits a final ``script_exit`` message.

        Args:
            script_text: Legacy script source code to execute.
            device_ids: Device ids to expose through the runtime facade.
            request_id: Request id associated with the active script run.

        Returns:
            None.
        """
        callbacks = ScriptHostCallbacks(
            print_callback=self._emit_script_output,
            wait_callback=default_wait_callback,
            abort_callback=self._emit_abort_request,
            command_callback=self._emit_command_request,
        )
        runtime = LegacyScriptRuntimeFacade(device_ids=device_ids, callbacks=callbacks)

        globals_dict = {
            "__name__": "__mints_script__",
            "print": runtime.print,
            "wait": runtime.wait,
            "abort": runtime.abort,
            "mints": runtime.mints,
            "exit": None,
        }

        return_code = 0
        failure_message: str | None = None
        try:
            exec(script_text, globals_dict, {})
        except (
            BaseException
        ) as exc:  # pragma: no cover - runtime path, covered via proxy/runner tests
            return_code = 1
            failure_message = f"{type(exc).__name__}: {exc}"
            self._emit_script_output(failure_message, level="error")
        finally:
            self.emit(
                build_message(
                    SCRIPT_HOST_MESSAGE_SCRIPT_EXIT,
                    {
                        "ok": return_code == 0,
                        "host_pid": os.getpid(),
                        "returncode": return_code,
                        "finished_at": isoformat_z(),
                        "failure_message": failure_message,
                    },
                    request_id=request_id,
                )
            )

    def _emit_script_output(self, *args: Any, **kwargs: Any) -> None:
        """Emit one script-output protocol message.

        Args:
            *args: Positional values received from the runtime print callback.
            **kwargs: Print-style keyword arguments such as ``sep`` and ``end``,
                plus an optional ``level`` field.

        Returns:
            None.
        """
        text = self._format_print_text(*args, **kwargs)
        level = kwargs.get("level") if isinstance(kwargs.get("level"), str) else "info"
        self.emit(
            build_message(
                SCRIPT_HOST_MESSAGE_SCRIPT_OUTPUT,
                {
                    "text": text,
                    "level": level,
                    "wall_time": isoformat_z(),
                },
                request_id=self._active_request_id,
            )
        )

    def _emit_abort_request(self, *args: Any, **kwargs: Any) -> None:
        """Emit a structured abort request generated by the running script.

        Args:
            *args: Positional abort arguments from the runtime facade. The first
                positional value is treated as the abort message when present.
            **kwargs: Keyword abort arguments from the runtime facade.

        Returns:
            None.
        """
        message = None
        if args:
            message = str(args[0])
        elif "message" in kwargs and kwargs["message"] is not None:
            message = str(kwargs["message"])
        self.emit(
            build_message(
                SCRIPT_HOST_MESSAGE_ABORT_REQUEST,
                {
                    "command_name": "abort",
                    "requested_via": "script_abort",
                    "message": message,
                    "command_args": [str(arg) for arg in args],
                    "command_kwargs": {
                        str(key): value for key, value in kwargs.items()
                    },
                    "wall_time": isoformat_z(),
                },
                request_id=self._active_request_id,
            )
        )

    def _emit_command_request(self, **kwargs: Any) -> None:
        """Emit a structured device-command request generated by the script.

        Args:
            **kwargs: Command metadata from the runtime facade, including the
                target device id, command name, and optional command args and
                kwargs.

        Returns:
            None.
        """
        payload = {
            "device_id": kwargs.get("device_id"),
            "command_name": kwargs.get("command_name"),
            "command_args": list(kwargs.get("command_args") or []),
            "command_kwargs": dict(kwargs.get("command_kwargs") or {}),
            "requested_via": "script_host",
            "wall_time": isoformat_z(),
        }
        self.emit(
            build_message(
                SCRIPT_HOST_MESSAGE_COMMAND_REQUEST,
                payload,
                request_id=self._active_request_id,
            )
        )

    def _format_print_text(self, *args: Any, **kwargs: Any) -> str:
        """Format print callback arguments into one emitted text line.

        Args:
            *args: Positional values to join into output text.
            **kwargs: Print-style keyword arguments such as ``sep`` and ``end``.

        Returns:
            The formatted output text with trailing newlines removed.
        """
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        if not isinstance(sep, str):
            sep = " "
        if not isinstance(end, str):
            end = "\n"
        text = sep.join(str(arg) for arg in args)
        if end:
            text = f"{text}{end}"
        return text.rstrip("\n")


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the script host process.

    Returns:
        Argument parser that accepts optional script-path and working-directory
        metadata for host startup.
    """
    parser = argparse.ArgumentParser(description="Run the minTS subprocess script host")
    parser.add_argument("--script-path", default=None)
    parser.add_argument("--cwd", default=None)
    return parser


def main() -> int:
    """Run the stdio script host process from command-line arguments.

    Returns:
        Exit status from ``ScriptHostServer.serve_forever``.
    """
    parser = _build_arg_parser()
    args = parser.parse_args()
    server = ScriptHostServer(script_path=args.script_path, cwd=args.cwd)
    return server.serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
