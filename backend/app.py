# backend/app.py

"""Backend service process bootstrap.

This module parses backend startup arguments, constructs ``BackendService``,
adopts any persisted gateway runtime status available at startup, and then
runs the backend IPC server until shutdown.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .service import BackendService


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the backend service process.

    Returns:
        The argument parser for backend startup options, including the project
        root and the backend and gateway Unix domain socket paths.
    """
    parser = argparse.ArgumentParser(description="Teststand backend service")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root used by backend services such as historymanager",
    )
    parser.add_argument(
        "--socket-path",
        type=Path,
        default=None,
        help="Unix domain socket path for GUI/backend IPC",
    )
    parser.add_argument(
        "--gateway-socket",
        type=Path,
        default=None,
        help="Unix domain socket path for backend/gateway IPC",
    )
    return parser


def main() -> int:
    """Start the backend service process and serve backend IPC until shutdown.

    The startup flow parses command-line arguments, constructs
    ``BackendService``, adopts any gateway runtime status that survived from an
    earlier gateway process, logs the adopted state summary, and then starts
    the backend IPC server. The service is always stopped in the shutdown path.

    Returns:
        Process exit status code. Returns ``0`` after normal shutdown or a
        keyboard-interrupt-driven stop.
    """
    parser = build_arg_parser()
    args = parser.parse_args()

    service = BackendService(
        project_root=args.project_root,
        socket_path=args.socket_path,
        gateway_socket_path=args.gateway_socket,
    )

    adopted_gateway_status = service.adopt_gateway_runtime_status()
    if adopted_gateway_status is None:
        print("[backend] no gateway runtime state adopted at startup")
    else:
        print(
            "[backend] adopted gateway runtime state "
            f"(bus_connected={adopted_gateway_status.get('bus_connected')}, "
            f"raw_run_active={adopted_gateway_status.get('raw_run_active')})"
        )

    try:
        print(f"[backend] starting IPC server at {service.socket_path}")
        service.serve_forever()
    except KeyboardInterrupt:
        print("[backend] stopping due to keyboard interrupt")
    finally:
        service.stop()

    return 0
