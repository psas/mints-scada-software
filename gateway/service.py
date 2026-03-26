from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from .models import GatewayRuntimeConfig

log = logging.getLogger(__name__)


class GatewayService:
    """Minimal gateway process scaffold.

    This commit intentionally adds only the process shell:
    - startup/shutdown lifecycle
    - placeholder serve loop
    - future home for bus ownership / raw/rawbak ownership

    It does NOT yet:
    - own the live bus
    - expose IPC
    - write raw/rawbak
    - communicate with backend
    """

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        idle_sleep_s: float = 0.25,
    ) -> None:
        if project_root is None:
            project_root = Path(__file__).resolve().parents[1]

        self.config = GatewayRuntimeConfig(
            project_root=project_root,
            idle_sleep_s=idle_sleep_s,
        )
        self._stop_event = threading.Event()
        self._started = False

    @property
    def project_root(self) -> Path:
        return self.config.project_root

    @property
    def idle_sleep_s(self) -> float:
        return self.config.idle_sleep_s

    @property
    def is_running(self) -> bool:
        return self._started and not self._stop_event.is_set()

    def start(self) -> None:
        """Start the gateway service lifecycle."""
        if self._started:
            log.debug("GatewayService.start() called while already started")
            return

        self._stop_event.clear()
        self._started = True
        log.info("Gateway service started (project_root=%s)", self.project_root)

    def serve_forever(self) -> None:
        """Run the placeholder gateway loop until stopped."""
        if not self._started:
            self.start()

        log.info("Gateway service entering idle loop")
        try:
            while not self._stop_event.is_set():
                time.sleep(self.idle_sleep_s)
        finally:
            log.info("Gateway service leaving idle loop")

    def stop(self) -> None:
        """Request gateway shutdown and perform best-effort cleanup."""
        if not self._started:
            return

        if self._stop_event.is_set():
            return

        log.info("Gateway service stopping")
        self._stop_event.set()
        self._started = False