"""gateway/app.py

Gateway service process bootstrap and signal wiring.

This module configures process-level logging, parses the gateway CLI, installs
shutdown signal handlers, and runs the gateway service loop for the live
hardware-edge process.
"""

from __future__ import annotations

import argparse
import logging
import signal
from pathlib import Path

from .service import GatewayService

LOG_FORMAT = "%(asctime)s [%(name)-16.16s] [%(levelname)-5.5s] %(message)s"


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the gateway service process.

    Returns:
        An argument parser configured with the project root, gateway socket,
        backend socket, and reserved idle-sleep runtime options.
    """
    parser = argparse.ArgumentParser(description="Teststand gateway service")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root used by the gateway service",
    )
    parser.add_argument(
        "--socket-path",
        type=Path,
        default=None,
        help="Unix domain socket path for backend/gateway IPC",
    )
    parser.add_argument(
        "--backend-socket",
        type=Path,
        default=None,
        help="Unix domain socket path for gateway -> backend IPC",
    )
    parser.add_argument(
        "--idle-sleep",
        type=float,
        default=0.25,
        help="Reserved placeholder runtime value for future gateway use",
    )
    return parser


def configure_logging() -> None:
    """Configure process-wide logging for the gateway service entrypoint.

    Returns:
        None.
    """
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
    )


def install_signal_handlers(service: GatewayService) -> None:
    """Install SIGTERM and SIGINT handlers that stop the gateway service.

    Args:
        service: Gateway service instance to stop when the process receives a
            termination signal.

    Returns:
        None.
    """

    def _handle_signal(signum, _frame) -> None:
        """Stop the service after logging the received process signal.

        Args:
            signum: Numeric signal value received by the process.
            _frame: Current stack frame supplied by the signal handler API.

        Returns:
            None.
        """
        logging.getLogger(__name__).info(
            "Stopping gateway due to signal %s",
            signum,
        )
        service.stop()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)


def main() -> int:
    """Run the gateway service process from CLI arguments.

    This configures logging, parses runtime options, builds the
    ``GatewayService`` instance, installs shutdown signal handlers, and blocks
    in the service loop until the process is interrupted or stopped.

    Returns:
        Zero when the gateway process exits cleanly.
    """
    configure_logging()
    parser = build_arg_parser()
    args = parser.parse_args()

    service = GatewayService(
        project_root=args.project_root,
        socket_path=args.socket_path,
        backend_socket_path=args.backend_socket,
        idle_sleep_s=args.idle_sleep,
    )
    install_signal_handlers(service)

    try:
        logging.getLogger(__name__).info(
            "Starting gateway service at socket %s",
            service.socket_path,
        )
        service.serve_forever()
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Stopping gateway due to keyboard interrupt")
        service.stop()
    finally:
        service.stop()

    return 0
