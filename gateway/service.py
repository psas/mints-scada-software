from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .ipc_models import (
    GatewayIPCMessage,
    error_message,
    gateway_status_message,
    hello_ack_message,
    pong_message,
)
from .ipc_server import GatewayIPCServer
from .models import GatewayRuntimeConfig

log = logging.getLogger(__name__)


def isoformat_z() -> str:
    """Return an ISO-8601 UTC timestamp with a trailing Z."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class GatewayService:
    """Gateway process scaffold with placeholder backend IPC.

    This commit adds:
    - a Unix socket IPC server for backend/gateway communication
    - hello/ping/status_request handling
    - connected-client tracking

    It still does NOT yet:
    - own the live bus
    - write raw/rawbak
    - proxy outbound commands
    """

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        socket_path: Path | None = None,
        idle_sleep_s: float = 0.25,
    ) -> None:
        if project_root is None:
            project_root = Path(__file__).resolve().parents[1]
        else:
            project_root = Path(project_root).expanduser().resolve()

        if socket_path is None:
            socket_path = project_root / ".gateway_service.sock"
        else:
            socket_path = Path(socket_path).expanduser().resolve()

        self.config = GatewayRuntimeConfig(
            project_root=project_root,
            socket_path=socket_path,
            idle_sleep_s=idle_sleep_s,
        )

        self.service_name = "teststand-gateway"
        self.started_at = isoformat_z()
        self.supported_messages = [
            "hello",
            "ping",
            "status_request",
        ]

        self._lock = threading.RLock()
        self._connected_clients: set[str] = set()
        self._started = False

        self.server = GatewayIPCServer(
            socket_path=self.socket_path,
            on_message=self.handle_message,
            on_client_connected=self.on_client_connected,
            on_client_disconnected=self.on_client_disconnected,
        )

    @property
    def project_root(self) -> Path:
        return self.config.project_root

    @property
    def socket_path(self) -> Path:
        return self.config.socket_path

    @property
    def connected_client_count(self) -> int:
        with self._lock:
            return len(self._connected_clients)

    @property
    def is_running(self) -> bool:
        return self._started

    def start(self) -> None:
        """Mark the gateway service as started."""
        if self._started:
            log.debug("GatewayService.start() called while already started")
            return
        self._started = True
        log.info(
            "Gateway service started (project_root=%s, socket_path=%s)",
            self.project_root,
            self.socket_path,
        )

    def serve_forever(self) -> None:
        """Run the gateway IPC server until stopped."""
        if not self._started:
            self.start()

        log.info("Gateway service starting IPC server at %s", self.socket_path)
        try:
            self.server.serve_forever()
        finally:
            log.info("Gateway service IPC server exited")

    def stop(self) -> None:
        """Request gateway shutdown and perform best-effort cleanup."""
        if not self._started:
            return

        log.info("Gateway service stopping")
        self.server.stop()
        self._started = False

    def on_client_connected(self, client_id: str) -> None:
        """Track a connected IPC client."""
        with self._lock:
            self._connected_clients.add(client_id)
        log.info("Gateway IPC client connected: %s", client_id)

    def on_client_disconnected(self, client_id: str) -> None:
        """Track a disconnected IPC client."""
        with self._lock:
            self._connected_clients.discard(client_id)
        log.info("Gateway IPC client disconnected: %s", client_id)

    def _build_status_message(self) -> GatewayIPCMessage:
        """Build the current gateway status payload."""
        return gateway_status_message(
            service_name=self.service_name,
            gateway_started_at=self.started_at,
            socket_path=str(self.socket_path),
            connected_clients=self.connected_client_count,
            supported_messages=self.supported_messages,
        )

    def handle_message(
        self,
        client_id: str,
        message: GatewayIPCMessage,
    ) -> Iterable[GatewayIPCMessage]:
        """Handle a single gateway IPC request."""
        if message.type == "hello":
            yield hello_ack_message(
                service_name=self.service_name,
                gateway_started_at=self.started_at,
                connected_clients=self.connected_client_count,
                supported_messages=self.supported_messages,
            )
            yield self._build_status_message()
            return

        if message.type == "ping":
            yield pong_message()
            return

        if message.type == "status_request":
            yield self._build_status_message()
            return

        yield error_message(
            code="unsupported_message",
            message=f"Unsupported gateway IPC message type: {message.type}",
            details={
                "client_id": client_id,
                "supported_messages": self.supported_messages,
            },
        )