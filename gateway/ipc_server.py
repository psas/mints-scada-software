# gateway/ipc_server.py

"""Unix socket IPC server for gateway-side JSON-lines message exchange.

This module hosts the gateway-facing IPC server used by peer processes such as
the backend. It accepts Unix domain socket connections, decodes one JSON-lines
message at a time, forwards each message to the configured handler, and writes
zero or more encoded response messages back to the same client.
"""

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
    """Serve gateway IPC clients over a Unix domain socket.

    The server accepts JSON-lines messages from connected clients, dispatches
    them through the configured message callback, and streams any returned
    response messages back to the same client connection. Each client is handled
    on its own daemon thread, while the main server loop remains responsible for
    accepting new connections and coordinating shutdown.
    """

    def __init__(
        self,
        *,
        socket_path: str | Path,
        on_message: Callable[[str, GatewayIPCMessage], Iterable[GatewayIPCMessage]],
        on_client_connected: Callable[[str], None] | None = None,
        on_client_disconnected: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize the gateway IPC server.

        Args:
            socket_path: Filesystem path for the Unix domain socket listener.
            on_message: Callback invoked for each decoded client message. It
                receives the generated client id and the decoded IPC message,
                and returns zero or more response messages to write back.
            on_client_connected: Optional callback invoked after a client is
                accepted and registered.
            on_client_disconnected: Optional callback invoked after a client
                connection is cleaned up and removed from the active registry.
        """
        self.socket_path = Path(socket_path).expanduser().resolve()
        self.on_message = on_message
        self.on_client_connected = on_client_connected
        self.on_client_disconnected = on_client_disconnected

        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._server_socket: socket.socket | None = None
        self._connections: dict[str, socket.socket] = {}

    def _prepare_socket_path(self) -> None:
        """Create the socket directory and remove any stale socket file."""
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass

    def serve_forever(self) -> None:
        """Accept and serve IPC clients until the server is stopped.

        This method creates the Unix domain listener, accepts client
        connections, assigns each client a generated id, and starts a daemon
        thread running ``_handle_client`` for each accepted connection. When the
        loop exits, it delegates final cleanup to ``stop()``.

        Returns:
            None.

        Raises:
            OSError: Propagated when the listener fails unexpectedly while the
                server is still supposed to be running.
        """
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
        """Process messages for one connected IPC client.

        The handler reads newline-delimited messages from the client socket,
        decodes each message, passes it to ``on_message``, and writes any
        returned response messages back to the same connection. If message
        handling raises, the server emits a canonical ``gateway_ipc_error``
        response instead of terminating the client thread immediately. The
        method also owns final per-client cleanup and disconnect callbacks.

        Args:
            client_id: Generated identifier for the connected client.
            conn: Accepted Unix domain socket for that client.

        Returns:
            None.
        """
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
        """Stop the server, close active connections, and remove the socket path.

        This is the shared shutdown path used by explicit stop requests and by
        ``serve_forever`` finalization. It closes the listener, closes any
        tracked client sockets, clears the active connection registry, and
        unlinks the Unix socket file if it still exists.

        Returns:
            None.
        """
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
