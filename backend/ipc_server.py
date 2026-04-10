# backend/ipc_server.py

"""Unix-domain IPC server for backend JSON-lines request handling.

This module provides the backend-side socket server used by local clients to
exchange line-delimited JSON IPC messages. Each accepted client connection is
handled on its own thread and routed through a caller-provided message handler.
"""

from __future__ import annotations

import socket
import threading
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

from .ipc_models import IPCMessage, error_message


MessageHandler = Callable[[str, IPCMessage], Iterable[IPCMessage]]
"""Callable that handles one decoded client message and yields zero or more responses."""

ClientHook = Callable[[str], None]
"""Callable invoked when a client connects or disconnects."""


class IPCServer:
    """Serve backend IPC messages over a Unix domain socket.

    The server accepts line-delimited JSON messages, decodes them into
    ``IPCMessage`` instances, and passes each request to ``on_message``. Each
    client connection is handled on a dedicated daemon thread.

    Args:
        socket_path: Filesystem path for the Unix domain socket.
        on_message: Callback that processes one decoded message and yields zero
            or more ``IPCMessage`` responses.
        on_client_connected: Optional callback invoked after a client thread is
            established.
        on_client_disconnected: Optional callback invoked when client handling
            finishes.
    """

    def __init__(
        self,
        *,
        socket_path: str | Path,
        on_message: MessageHandler,
        on_client_connected: ClientHook | None = None,
        on_client_disconnected: ClientHook | None = None,
    ) -> None:
        """Initialize the IPC server and its client lifecycle hooks.

        Args:
            socket_path: Filesystem path for the Unix domain socket.
            on_message: Callback that processes one decoded message and yields
                zero or more ``IPCMessage`` responses.
            on_client_connected: Optional callback invoked after a client thread
                is established.
            on_client_disconnected: Optional callback invoked when client
                handling finishes.
        """
        self.socket_path = Path(socket_path)
        self.on_message = on_message
        self.on_client_connected = on_client_connected
        self.on_client_disconnected = on_client_disconnected

        self._server_socket: socket.socket | None = None
        self._stop_event = threading.Event()
        self._client_threads: set[threading.Thread] = set()
        self._client_threads_lock = threading.Lock()

    def serve_forever(self) -> None:
        """Bind the socket path and serve clients until the server is stopped.

        This prepares the socket path, accepts Unix socket clients in a loop,
        and starts one daemon thread per accepted connection. The method exits
        when ``stop()`` sets the stop event or closes the listening socket.

        Returns:
            None.

        Raises:
            OSError: Propagated when socket setup or accept fails for reasons
                other than normal shutdown.
        """
        self._prepare_socket_path()

        server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_socket.bind(str(self.socket_path))
        server_socket.listen()
        server_socket.settimeout(1.0)

        self._server_socket = server_socket

        try:
            while not self._stop_event.is_set():
                try:
                    client_socket, _ = server_socket.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop_event.is_set():
                        break
                    raise

                client_id = uuid4().hex
                client_thread = threading.Thread(
                    target=self._handle_client,
                    name=f"backend-ipc-client-{client_id[:8]}",
                    args=(client_id, client_socket),
                    daemon=True,
                )

                with self._client_threads_lock:
                    self._client_threads.add(client_thread)

                client_thread.start()

        finally:
            try:
                server_socket.close()
            finally:
                self._server_socket = None
                self._cleanup_socket_path()

    def stop(self) -> None:
        """Request server shutdown and wake a blocking accept call.

        This sets the shared stop flag, closes the listening socket when one is
        active, and opens a temporary connection to the socket path so the
        accept loop can observe shutdown promptly.

        Returns:
            None.
        """
        self._stop_event.set()

        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass

        # Wake accept() if needed.
        try:
            wake_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            wake_socket.connect(str(self.socket_path))
            wake_socket.close()
        except OSError:
            pass

    def _handle_client(self, client_id: str, client_socket: socket.socket) -> None:
        """Process requests for one connected IPC client.

        The client loop reads line-delimited JSON messages, decodes each line
        into an ``IPCMessage``, passes it through ``on_message``, and writes all
        returned responses back to the same socket. Processing failures are
        converted into a single ``invalid_request`` error response.

        Args:
            client_id: Generated identifier for the connected client.
            client_socket: Connected Unix domain socket for the client.

        Returns:
            None.
        """
        if self.on_client_connected is not None:
            self.on_client_connected(client_id)

        try:
            with client_socket:
                read_handle = client_socket.makefile("r", encoding="utf-8")
                write_handle = client_socket.makefile("w", encoding="utf-8")

                with read_handle, write_handle:
                    for raw_line in read_handle:
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue

                        try:
                            request = IPCMessage.from_json(raw_line)
                            responses = list(self.on_message(client_id, request))
                        except Exception as exc:
                            responses = [
                                error_message(
                                    "invalid_request",
                                    f"Failed to process IPC message: {exc}",
                                )
                            ]

                        for response in responses:
                            write_handle.write(response.to_json())
                            write_handle.write("\n")
                        write_handle.flush()

                        if self._stop_event.is_set():
                            break

        finally:
            if self.on_client_disconnected is not None:
                self.on_client_disconnected(client_id)

            with self._client_threads_lock:
                current = threading.current_thread()
                self._client_threads.discard(current)

    def _prepare_socket_path(self) -> None:
        """Create the socket parent directory and remove any stale socket file.

        Returns:
            None.

        Raises:
            OSError: Propagated when directory creation or socket-path removal
                fails.
        """
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)

        if self.socket_path.exists():
            self.socket_path.unlink()

    def _cleanup_socket_path(self) -> None:
        """Best-effort removal of the Unix socket file after shutdown.

        Returns:
            None.
        """
        try:
            if self.socket_path.exists():
                self.socket_path.unlink()
        except OSError:
            pass
