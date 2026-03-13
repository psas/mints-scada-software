from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterable

from historymanager import HistoryManager
from historymanager.manager import isoformat_z

from .ipc_models import (
    IPCMessage,
    backend_status_message,
    error_message,
    hello_ack_message,
    pong_message,
)
from .ipc_server import IPCServer


class BackendService:
    """Minimal backend service skeleton.

    Commit 4 scope:
    - backend can start independently
    - backend exposes a Unix-socket IPC server
    - backend accepts hello/ping/status_request
    - backend owns HistoryManager instance

    This does not yet own Bus, reducer, or authoritative state store.
    Those will be added in later commits.
    """

    def __init__(
        self,
        *,
        project_root: str | Path | None = None,
        socket_path: str | Path | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve() if project_root else None
        self.history_manager = HistoryManager(project_root=project_root)

        if socket_path is None:
            if self.project_root is None:
                socket_path = Path(".backend_service.sock").resolve()
            else:
                socket_path = self.project_root / ".backend_service.sock"

        self.socket_path = Path(socket_path).expanduser().resolve()
        self.started_at = isoformat_z()
        self.service_name = "teststand-backend"

        self._lock = threading.RLock()
        self._connected_clients: set[str] = set()

        self.supported_messages = [
            "hello",
            "ping",
            "status_request",
        ]

        self.server = IPCServer(
            socket_path=self.socket_path,
            on_message=self.handle_message,
            on_client_connected=self.on_client_connected,
            on_client_disconnected=self.on_client_disconnected,
        )

    def serve_forever(self) -> None:
        self.server.serve_forever()

    def stop(self) -> None:
        self.server.stop()

    def on_client_connected(self, client_id: str) -> None:
        with self._lock:
            self._connected_clients.add(client_id)

    def on_client_disconnected(self, client_id: str) -> None:
        with self._lock:
            self._connected_clients.discard(client_id)

    def handle_message(self, client_id: str, message: IPCMessage) -> Iterable[IPCMessage]:
        if message.type == "hello":
            yield hello_ack_message(
                service_name=self.service_name,
                backend_started_at=self.started_at,
                connected_clients=self.connected_client_count,
                supported_messages=self.supported_messages,
            )
            yield self._build_backend_status_message()
            return

        if message.type == "ping":
            yield pong_message()
            return

        if message.type == "status_request":
            yield self._build_backend_status_message()
            return

        yield error_message(
            "unsupported_message_type",
            f"Unsupported IPC message type: {message.type}",
        )

    @property
    def connected_client_count(self) -> int:
        with self._lock:
            return len(self._connected_clients)

    def _build_backend_status_message(self) -> IPCMessage:
        active_run_id = None
        is_running = False

        if self.history_manager.current_run is not None:
            active_run_id = self.history_manager.current_run.run_id
            is_running = self.history_manager.is_running

        return backend_status_message(
            backend_started_at=self.started_at,
            connected_clients=self.connected_client_count,
            active_run_id=active_run_id,
            is_running=is_running,
        )