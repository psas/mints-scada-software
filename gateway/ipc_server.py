from __future__ import annotations

import logging
import socket
import threading
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

from .ipc_models import GatewayIPCMessage, decode_message, encode_message, error_message

log = logging.getLogger(__name__)


class GatewayIPCServer:
    """Simple JSON-lines Unix socket server for gateway/backend IPC."""

    def __init__(
        self,
        *,
        socket_path: str | Path,
        on_message: Callable[[str, GatewayIPCMessage], Iterable[GatewayIPCMessage]],
        on_client_connected: Callable[[str], None] | None = None,
        on_client_disconnected: Callable[[str], None] | None = None,
    ) -> None:
        self.socket_path = Path(socket_path).expanduser().resolve()
        self.on_message = on_message
        self.on_client_connected = on_client_connected
        self.on_client_disconnected = on_client_disconnected

        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._server_socket: socket.socket | None = None
        self._connections: dict[str, socket.socket] = {}

    def _prepare_socket_path(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass

    def serve_forever(self) -> None:
        """Serve clients until stopped."""
        self._stop_event.clear()
        self._prepare_socket_path()

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        server.listen()
        server.settimeout(0.5)
        self._server_socket = server

        log.info("Gateway IPC server listening at %s", self.socket_path)

        try:
            while not self._stop_event.is_set():
                try:
                    conn, _addr = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop_event.is_set():
                        break
                    raise

                client_id = uuid4().hex
                with self._lock:
                    self._connections[client_id] = conn

                if self.on_client_connected is not None:
                    try:
                        self.on_client_connected(client_id)
                    except Exception:
                        log.exception("Gateway on_client_connected callback failed")

                thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_id, conn),
                    daemon=True,
                )
                thread.start()
        finally:
            self.stop()

    def _handle_client(self, client_id: str, conn: socket.socket) -> None:
        reader = conn.makefile("rb")
        writer = conn.makefile("wb")

        try:
            while not self._stop_event.is_set():
                try:
                    line = reader.readline()
                except OSError:
                    break

                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                try:
                    message = decode_message(line)
                    responses = list(self.on_message(client_id, message))
                except Exception as exc:
                    log.exception("Gateway IPC message handling failed")
                    responses = [
                        error_message(
                            code="gateway_ipc_error",
                            message=str(exc),
                        )
                    ]

                try:
                    for response in responses:
                        writer.write(encode_message(response))
                        writer.write(b"\n")
                    writer.flush()
                except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                    log.debug(
                        "Gateway IPC client write failed during disconnect cleanup: %s",
                        exc,
                    )
                    break
        finally:
            try:
                reader.close()
            except Exception:
                pass
            try:
                writer.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

            with self._lock:
                self._connections.pop(client_id, None)

            if self.on_client_disconnected is not None:
                try:
                    self.on_client_disconnected(client_id)
                except Exception:
                    log.exception("Gateway on_client_disconnected callback failed")

    def stop(self) -> None:
        """Stop the IPC server and remove the socket file."""
        if self._stop_event.is_set():
            return

        self._stop_event.set()

        server = self._server_socket
        self._server_socket = None
        if server is not None:
            try:
                server.close()
            except Exception:
                pass

        with self._lock:
            connections = list(self._connections.values())
            self._connections.clear()

        for conn in connections:
            try:
                conn.close()
            except Exception:
                pass

        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass