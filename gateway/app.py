from __future__ import annotations

import argparse
import logging
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
        "--idle-sleep",
        type=float,
        default=0.25,
        help="Idle loop sleep interval in seconds",
    )
    return parser


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
    )


def main() -> int:
    configure_logging()
    parser = build_arg_parser()
    args = parser.parse_args()

    service = GatewayService(
        project_root=args.project_root,
        idle_sleep_s=args.idle_sleep,
    )

    try:
        logging.getLogger(__name__).info("Starting gateway service")
        service.serve_forever()
    except KeyboardInterrupt:
        logging.getLogger(__name__).info(
            "Stopping gateway due to keyboard interrupt"
        )
    finally:
        service.stop()

    return 0