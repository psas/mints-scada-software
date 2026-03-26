from __future__ import annotations

import argparse
import logging
import signal
from pathlib import Path

from .service import GatewayService

LOG_FORMAT = "%(asctime)s [%(name)-16.16s] [%(levelname)-5.5s] %(message)s"


def build_arg_parser() -> argparse.ArgumentParser:
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
        "--idle-sleep",
        type=float,
        default=0.25,
        help="Reserved placeholder runtime value for future gateway use",
    )
    return parser


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
    )


def install_signal_handlers(service: GatewayService) -> None:
    def _handle_signal(signum, _frame) -> None:
        logging.getLogger(__name__).info(
            "Stopping gateway due to signal %s",
            signum,
        )
        service.stop()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)


def main() -> int:
    configure_logging()
    parser = build_arg_parser()
    args = parser.parse_args()

    service = GatewayService(
        project_root=args.project_root,
        socket_path=args.socket_path,
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
        logging.getLogger(__name__).info(
            "Stopping gateway due to keyboard interrupt"
        )
        service.stop()
    finally:
        service.stop()

    return 0