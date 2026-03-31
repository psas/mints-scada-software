from __future__ import annotations

import argparse
import os
import sys
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
from scripts.script_runtime.script_protocol import (
    SCRIPT_HOST_MESSAGE_ERROR,
    SCRIPT_HOST_MESSAGE_HOST_READY,
    SCRIPT_HOST_MESSAGE_PING,
    SCRIPT_HOST_MESSAGE_PONG,
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
    """Stdio JSONL host scaffold for future isolated legacy script execution."""

    def __init__(self, *, script_path: str | None = None, cwd: str | None = None) -> None:
        self.script_path = script_path
        self.cwd = cwd
        self._running = True

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
            self.emit(response)
        return 0

    def _handle_request(self, request: Mapping[str, Any]) -> dict[str, Any]:
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

        raise ValueError(f"Unsupported script host request type: {request_type!r}")



def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the minTS subprocess script host scaffold")
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
