from __future__ import annotations

import argparse
from pathlib import Path

from .gateway_client import GatewayClient
from .service import BackendService


def build_arg_parser() -> argparse.ArgumentParser:
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
    parser = build_arg_parser()
    args = parser.parse_args()

    service = BackendService(
        project_root=args.project_root,
        socket_path=args.socket_path,
    )

    gateway_client = GatewayClient(
        project_root=args.project_root,
        socket_path=args.gateway_socket,
    )

    hello_responses = gateway_client.hello(
        service_name=service.service_name,
        backend_socket_path=str(service.socket_path),
    )
    if hello_responses:
        print(f"[backend] gateway IPC reachable at {gateway_client.socket_path}")
    else:
        print(
            f"[backend] gateway IPC not available at {gateway_client.socket_path}; "
            "continuing without gateway link"
        )

    try:
        print(f"[backend] starting IPC server at {service.socket_path}")
        service.serve_forever()
    except KeyboardInterrupt:
        print("[backend] stopping due to keyboard interrupt")
    finally:
        service.stop()

    return 0