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
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int((time.time() % 1) * 1000):03d}Z"


class ScriptHostServer:
    """Stdio JSONL host for isolated legacy script execution."""

    def __init__(self, *, script_path: str | None = None, cwd: str | None = None) -> None:
        self.script_path = script_path
        self.cwd = cwd
        self._running = True
        self._script_thread: threading.Thread | None = None
        self._script_lock = threading.RLock()
        self._active_request_id: str | None = None

    def emit(self, payload: Mapping[str, Any]) -> None:
        sys.stdout.buffer.write(encode_json_line(payload))
        sys.stdout.buffer.flush()

    def emit_ready(self) -> None:
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
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("execute_legacy_script requires a non-empty string request_id")

        with self._script_lock:
            if self._script_thread is not None and self._script_thread.is_alive():
                raise RuntimeError("A legacy script is already running in this host")

            script_text = payload.get("script_text")
            if not isinstance(script_text, str) or not script_text.strip():
                raise ValueError("execute_legacy_script requires a non-empty 'script_text'")

            device_ids_value = payload.get("device_ids") or []
            if not isinstance(device_ids_value, list):
                raise ValueError("execute_legacy_script field 'device_ids' must be a list when provided")
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

    def _run_legacy_script(self, script_text: str, device_ids: list[str], request_id: str) -> None:
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
        except BaseException as exc:  # pragma: no cover - runtime path, covered via proxy/runner tests
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
                    "command_kwargs": {str(key): value for key, value in kwargs.items()},
                    "wall_time": isoformat_z(),
                },
                request_id=self._active_request_id,
            )
        )

    def _emit_command_request(self, **kwargs: Any) -> None:
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
    parser = argparse.ArgumentParser(description="Run the minTS subprocess script host")
    parser.add_argument("--script-path", default=None)
    parser.add_argument("--cwd", default=None)
    return parser



def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()
    server = ScriptHostServer(script_path=args.script_path, cwd=args.cwd)
    return server.serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
