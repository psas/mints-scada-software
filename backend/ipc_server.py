from __future__ import annotations

import socket
import threading
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

from .ipc_models import IPCMessage, error_message


MessageHandler = Callable[[str, IPCMessage], Iterable[IPCMessage]]
ClientHook = Callable[[str], None]


class IPCServer:
    """Simple JSON-lines IPC server over a Unix domain socket.

    This is intentionally small for the first backend skeleton:
    - one socket path
    - one thread per client
    - line-delimited JSON messages
    - message handler returns zero or more IPCMessage responses
    """

    def __init__(
        self,
        *,
        socket_path: str | Path,
        on_message: MessageHandler,
        on_client_connected: ClientHook | None = None,
        on_client_disconnected: ClientHook | None = None,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.on_message = on_message
        self.on_client_connected = on_client_connected
        self.on_client_disconnected = on_client_disconnected

        self._server_socket: socket.socket | None = None
        self._stop_event = threading.Event()
        self._client_threads: set[threading.Thread] = set()
        self._client_threads_lock = threading.Lock()

    def serve_forever(self) -> None:
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
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)

        if self.socket_path.exists():
            self.socket_path.unlink()

    def _cleanup_socket_path(self) -> None:
        try:
            if self.socket_path.exists():
                self.socket_path.unlink()
        except OSError:
            pass