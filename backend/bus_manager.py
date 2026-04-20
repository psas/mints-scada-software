"""backend/bus_manager.py

Backend-owned bus lifecycle management with reconnect supervision.

This module wraps the live ``nexus.Bus`` instance used by the backend. It
coordinates bus startup and shutdown, device registration, optional packet
listener attachment, optional polling-based receive loops, reconnect
supervision, and status/error fanout callbacks for the rest of the backend.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import settings
from nexus import Bus

from .device_registry import DeviceRegistry

log = logging.getLogger(__name__)


BusStatusCallback = Callable[[dict[str, Any]], None]
BusPacketCallback = Callable[[Any], None]
BusErrorCallback = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class BusInitResult:
    """Summarize the outcome of live bus initialization and device registration.

    Attributes:
        sender: Bus sender identifier used for the connection.
        bitrate: Bus bitrate used for the connection.
        registered_ids: Device IDs successfully registered on the live bus.
        skipped_ids: Device IDs skipped during registration.
        registered_count: Number of registered devices.
        skipped_count: Number of skipped devices.
        already_running: Whether initialization returned a cached result because
            the bus was already running.
    """

    sender: str
    bitrate: int
    registered_ids: list[str]
    skipped_ids: list[str]
    registered_count: int
    skipped_count: int
    already_running: bool = False


class BusManager:
    """Manage backend-owned live bus lifecycle, packet intake, and reconnects.

    The manager keeps the backend-facing bus API stable while adding service-side
    supervision hooks. It opens and closes the live bus, registers active
    devices, optionally attaches listener-based packet callbacks, optionally
    starts a polling receive loop for pull-style bus implementations, and can
    reconnect automatically after disconnects or repeated receive failures.
    """

    def __init__(
        self,
        *,
        sender: str | None = None,
        bitrate: int | None = None,
        packetprinting: bool = False,
        packetlogging: bool = False,
        auto_reconnect: bool = True,
        reconnect_initial_delay: float = 0.50,
        reconnect_max_delay: float = 5.00,
        reconnect_backoff: float = 2.00,
        receive_poll_interval: float = 0.05,
        monitor_interval: float = 0.50,
        max_receive_failures_before_reconnect: int = 3,
    ) -> None:
        """Initialize the bus manager and reconnect policy.

        Args:
            sender: Bus sender identifier. Falls back to ``settings.sender``.
            bitrate: Bus bitrate. Falls back to ``settings.bitrate``.
            packetprinting: Whether to enable packet printing on the bus.
            packetlogging: Whether to enable packet logging on the bus.
            auto_reconnect: Whether to reconnect automatically after failures.
            reconnect_initial_delay: Initial reconnect delay in seconds.
            reconnect_max_delay: Maximum reconnect delay in seconds.
            reconnect_backoff: Multiplicative backoff factor for reconnects.
            receive_poll_interval: Poll interval for pull-style receive loops.
            monitor_interval: Supervisor loop sleep interval in seconds.
            max_receive_failures_before_reconnect: Number of consecutive receive
                failures that triggers a forced disconnect and reconnect path.
        """
        self.sender = sender if sender is not None else settings.sender
        self.bitrate = bitrate if bitrate is not None else settings.bitrate
        self.packetprinting = packetprinting
        self.packetlogging = packetlogging

        self.auto_reconnect = auto_reconnect
        self.reconnect_initial_delay = max(0.05, float(reconnect_initial_delay))
        self.reconnect_max_delay = max(
            self.reconnect_initial_delay, float(reconnect_max_delay)
        )
        self.reconnect_backoff = max(1.10, float(reconnect_backoff))
        self.receive_poll_interval = max(0.01, float(receive_poll_interval))
        self.monitor_interval = max(0.05, float(monitor_interval))
        self.max_receive_failures_before_reconnect = max(
            1, int(max_receive_failures_before_reconnect)
        )

        self._lock = threading.RLock()
        self._bus: Bus | None = None
        self._entered = False
        self._registry: DeviceRegistry | None = None
        self._last_init_result: BusInitResult | None = None

        self._status_callback: BusStatusCallback | None = None
        self._packet_callback: BusPacketCallback | None = None
        self._error_callback: BusErrorCallback | None = None

        self._supervisor_thread: threading.Thread | None = None
        self._receive_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._receive_stop_event = threading.Event()

        self._manual_shutdown = False
        self._packet_listener_attached = False
        self._receive_failures = 0
        self._next_reconnect_not_before = 0.0

    @property
    def bus(self) -> Bus | None:
        """Return the current live bus instance when one is active.

        Returns:
            The active ``Bus`` instance, or None when the manager is not
            connected.
        """
        return self._bus

    @property
    def is_running(self) -> bool:
        """Return whether the live bus is currently open.

        Returns:
            True when a bus instance exists and its context manager has been
            entered successfully.
        """
        return self._bus is not None and self._entered

    @property
    def last_init_result(self) -> BusInitResult | None:
        """Return the most recent initialization summary.

        Returns:
            The cached ``BusInitResult`` from the most recent successful live
            initialization, or None when initialization has not completed yet.
        """
        return self._last_init_result

    def set_event_callbacks(
        self,
        *,
        status_callback: BusStatusCallback | None = None,
        packet_callback: BusPacketCallback | None = None,
        error_callback: BusErrorCallback | None = None,
    ) -> None:
        """Register service-side callbacks for bus lifecycle events.

        Args:
            status_callback: Callback for status messages such as connect,
                disconnect, receive loop, and reconnect events.
            packet_callback: Callback invoked for each received packet that
                reaches the manager.
            error_callback: Callback invoked when bus lifecycle, listener, or
                packet-handling errors occur.
        """
        self._status_callback = status_callback
        self._packet_callback = packet_callback
        self._error_callback = error_callback

    def initialize_live_hardware(self, registry: DeviceRegistry) -> BusInitResult:
        """Open the live bus, register devices, and start supervision.

        If the bus is already running, this returns a cached initialization
        summary marked as ``already_running=True`` instead of reopening the bus.

        Args:
            registry: Device registry used to register active devices with the
                live bus.

        Returns:
            A summary of device registration and connection parameters.

        Raises:
            Exception: Propagates bus construction, entry, or registration
                failures from the underlying bus or registry.
        """
        with self._lock:
            if self.is_running:
                if self._last_init_result is not None:
                    cached = self._last_init_result
                    return BusInitResult(
                        sender=cached.sender,
                        bitrate=cached.bitrate,
                        registered_ids=list(cached.registered_ids),
                        skipped_ids=list(cached.skipped_ids),
                        registered_count=cached.registered_count,
                        skipped_count=cached.skipped_count,
                        already_running=True,
                    )
                # Running but no cached result (should not happen in practice).
                return BusInitResult(
                    sender=self.sender,
                    bitrate=self.bitrate,
                    registered_ids=[],
                    skipped_ids=[],
                    registered_count=0,
                    skipped_count=0,
                    already_running=True,
                )

            self._registry = registry
            self._manual_shutdown = False
            self._stop_event.clear()
            self._receive_stop_event.clear()

            result = self._open_bus_and_register(registry)
            self._start_supervisor_thread_locked()
            self._start_receive_loop_if_supported_locked()
            return result

    def shutdown_live_hardware(self) -> None:
        """Stop supervision, close the live bus, and join background threads.

        Returns:
            None.
        """
        with self._lock:
            self._manual_shutdown = True
            self._stop_event.set()
            self._receive_stop_event.set()
            self._safe_shutdown_current_bus_locked(reason="manual_shutdown")

        self._join_background_threads()

    def _open_bus_and_register(self, registry: DeviceRegistry) -> BusInitResult:
        """Create a live bus connection and register active devices.

        This stores the connected bus, attaches packet intake when supported,
        resets receive-failure counters, caches the initialization summary, and
        emits a connected status event.

        Args:
            registry: Device registry used to register active devices with the
                new bus instance.

        Returns:
            A summary of bus connection parameters and registration results.

        Raises:
            Exception: Propagates failures from bus entry or device registration
                after emitting an initialization error and shutting down the
                partially opened bus.
        """
        bus = Bus(
            self.sender,
            self.bitrate,
            packetprinting=self.packetprinting,
            packetlogging=self.packetlogging,
        )

        try:
            bus.__enter__()
            registration = registry.register_active_devices_with_bus(bus)

            self._bus = bus
            self._entered = True
            self._packet_listener_attached = self._try_attach_packet_listener(bus)
            self._receive_failures = 0

            result = BusInitResult(
                sender=self.sender,
                bitrate=self.bitrate,
                registered_ids=list(registration["registered_ids"]),
                skipped_ids=list(registration["skipped_ids"]),
                registered_count=int(registration["registered_count"]),
                skipped_count=int(registration["skipped_count"]),
            )
            self._last_init_result = result

            self._emit_status(
                "connected",
                reason=(
                    "initial_connect"
                    if self._next_reconnect_not_before == 0.0
                    else "reconnect_success"
                ),
                sender=result.sender,
                bitrate=result.bitrate,
                registered_ids=list(result.registered_ids),
                skipped_ids=list(result.skipped_ids),
                registered_count=result.registered_count,
                skipped_count=result.skipped_count,
                packet_listener_attached=self._packet_listener_attached,
            )
            return result
        except Exception as exc:
            self._emit_error(
                "bus_initialize_failed",
                exc,
                sender=self.sender,
                bitrate=self.bitrate,
            )
            self._safe_shutdown_specific_bus(bus)
            raise

    def _start_supervisor_thread_locked(self) -> None:
        """Start the reconnect supervisor thread when it is not already running.

        Returns:
            None.
        """
        if self._supervisor_thread is not None and self._supervisor_thread.is_alive():
            return

        self._supervisor_thread = threading.Thread(
            target=self._supervisor_loop,
            name="backend-bus-supervisor",
            daemon=True,
        )
        self._supervisor_thread.start()

    def _start_receive_loop_if_supported_locked(self) -> None:
        """Start a polling receive loop for pull-style bus implementations.

        The receive loop is skipped when a listener-based packet path has
        already been attached, when the bus does not expose a recognized receive
        method, or when a receive thread is already active.

        Returns:
            None.
        """
        self._receive_stop_event.clear()

        if self._packet_listener_attached:
            return

        receive_callable = self._resolve_receive_callable(self._bus)
        if receive_callable is None:
            return

        if self._receive_thread is not None and self._receive_thread.is_alive():
            return

        self._receive_thread = threading.Thread(
            target=self._receive_loop,
            args=(receive_callable,),
            name="backend-bus-receive",
            daemon=True,
        )
        self._receive_thread.start()
        self._emit_status("receive_loop_started", mode="poll")

    def _receive_loop(self, receive_callable: Callable[[], Any]) -> None:
        """Poll packets from a pull-style bus API until stopped or disconnected.

        Consecutive receive failures are counted. Once the failure threshold is
        reached, the current bus is shut down so the supervisor can reconnect.

        Args:
            receive_callable: Zero-argument callable that returns the next
                packet, returns None when no packet is available, or raises on
                receive failure.

        Returns:
            None.
        """
        while not self._receive_stop_event.is_set() and not self._stop_event.is_set():
            if not self.is_running:
                time.sleep(self.receive_poll_interval)
                continue

            try:
                packet = receive_callable()
            except Exception as exc:
                self._receive_failures += 1
                self._emit_error(
                    "bus_receive_failed",
                    exc,
                    failure_count=self._receive_failures,
                    sender=self.sender,
                    bitrate=self.bitrate,
                )
                if self._receive_failures >= self.max_receive_failures_before_reconnect:
                    with self._lock:
                        self._safe_shutdown_current_bus_locked(reason="receive_failure")
                    break
                time.sleep(self.receive_poll_interval)
                continue

            self._receive_failures = 0

            if packet is None:
                time.sleep(self.receive_poll_interval)
                continue

            self._handle_packet(packet)

        self._emit_status("receive_loop_stopped")

    def _supervisor_loop(self) -> None:
        """Reconnect the live bus with exponential backoff when it drops.

        The supervisor runs until global shutdown. It only attempts reconnects
        when automatic reconnect is enabled, shutdown was not manual, a device
        registry is available, and the bus is currently disconnected.

        Returns:
            None.
        """
        backoff = self.reconnect_initial_delay

        while not self._stop_event.is_set():
            time.sleep(self.monitor_interval)

            if not self.auto_reconnect or self._manual_shutdown:
                continue

            with self._lock:
                registry = self._registry
                should_reconnect = registry is not None and not self.is_running

            if not should_reconnect:
                continue

            now = time.monotonic()
            if now < self._next_reconnect_not_before:
                continue

            self._emit_status(
                "reconnecting",
                delay_seconds=round(backoff, 3),
                sender=self.sender,
                bitrate=self.bitrate,
            )

            try:
                with self._lock:
                    if self._registry is None or self._manual_shutdown:
                        continue
                    self._receive_stop_event.clear()
                    self._open_bus_and_register(self._registry)
                    self._start_receive_loop_if_supported_locked()
                    self._next_reconnect_not_before = 0.0
                backoff = self.reconnect_initial_delay
            except Exception:
                self._next_reconnect_not_before = time.monotonic() + backoff
                backoff = min(
                    self.reconnect_max_delay, backoff * self.reconnect_backoff
                )

    def _resolve_receive_callable(self, bus: Bus | None) -> Callable[[], Any] | None:
        """Resolve a polling receive callable from a bus instance.

        The returned wrapper prefers timeout-aware receive methods when the bus
        supports them and falls back to zero-argument calls otherwise.

        Args:
            bus: Active bus instance to inspect.

        Returns:
            A zero-argument receive callable, or None when the bus does not
            expose a recognized pull-style receive API.
        """
        if bus is None:
            return None

        for attr_name in (
            "receive",
            "recv",
            "read_packet",
            "get_packet",
            "next_packet",
        ):
            candidate = getattr(bus, attr_name, None)
            if not callable(candidate):
                continue

            def _call_candidate(candidate: Callable[..., Any] = candidate) -> Any:
                """Invoke the bus receive callable with optional timeout.

                Args:
                    candidate: The bus receive method to invoke.

                Returns:
                    The packet or value returned by the bus receive call.
                """
                try:
                    return candidate(timeout=self.receive_poll_interval)
                except TypeError:
                    return candidate()

            return _call_candidate

        return None

    def _try_attach_packet_listener(self, bus: Bus) -> bool:
        """Attach a listener-based packet callback when the bus supports it.

        The manager probes several common listener registration method names and
        binds ``self._handle_packet`` to the first compatible one.

        Args:
            bus: Active bus instance to configure.

        Returns:
            True when a listener hook was attached successfully. False when no
            compatible hook exists or every attempted attachment failed.
        """
        for attr_name in (
            "set_packet_listener",
            "set_listener",
            "add_packet_listener",
            "register_packet_listener",
        ):
            candidate = getattr(bus, attr_name, None)
            if not callable(candidate):
                continue

            try:
                candidate(self._handle_packet)
                self._emit_status("packet_listener_attached", method=attr_name)
                return True
            except Exception as exc:
                self._emit_error(
                    "bus_packet_listener_attach_failed",
                    exc,
                    method=attr_name,
                )
        return False

    def _handle_packet(self, packet: Any) -> None:
        """Forward a received packet to the registered packet callback.

        Args:
            packet: Packet produced by the live bus listener or receive loop.

        Returns:
            None.
        """
        callback = self._packet_callback
        if callback is None:
            return

        try:
            callback(packet)
        except Exception as exc:
            self._emit_error("bus_packet_callback_failed", exc)

    def _safe_shutdown_current_bus_locked(self, *, reason: str) -> None:
        """Disconnect and clear the currently active bus under the manager lock.

        This clears the active bus state first, stops receive polling, closes
        the old bus instance safely, and emits a disconnected status event when
        a bus was present.

        Args:
            reason: Disconnect reason reported in the emitted status payload.

        Returns:
            None.
        """
        bus = self._bus
        self._bus = None
        self._entered = False
        self._packet_listener_attached = False
        self._receive_stop_event.set()

        if bus is None:
            return

        self._safe_shutdown_specific_bus(bus)
        self._emit_status(
            "disconnected",
            reason=reason,
            sender=self.sender,
            bitrate=self.bitrate,
        )

    def _safe_shutdown_specific_bus(self, bus: Bus) -> None:
        """Close a specific bus instance and report shutdown failures.

        Args:
            bus: Bus instance to close.

        Returns:
            None.
        """
        try:
            bus.__exit__(None, None, None)
        except Exception as exc:
            self._emit_error(
                "bus_shutdown_failed",
                exc,
                sender=self.sender,
                bitrate=self.bitrate,
            )

    def _join_background_threads(self) -> None:
        """Join the receive and supervisor threads with short timeouts.

        Returns:
            None.
        """
        receive_thread = self._receive_thread
        supervisor_thread = self._supervisor_thread

        if receive_thread is not None and receive_thread.is_alive():
            receive_thread.join(timeout=1.0)
        if supervisor_thread is not None and supervisor_thread.is_alive():
            supervisor_thread.join(timeout=1.0)

        self._receive_thread = None
        self._supervisor_thread = None

    def _emit_status(self, event: str, **payload: Any) -> None:
        """Emit a bus status message through the registered status callback.

        Args:
            event: Status event name.
            **payload: Additional status fields to include in the emitted
                message.

        Returns:
            None.
        """
        callback = self._status_callback
        if callback is None:
            return

        message = {
            "event": event,
            "wall_time": time.time(),
            **payload,
        }
        try:
            callback(message)
        except Exception:
            log.exception("Bus status callback failed")

    def _emit_error(self, error_type: str, exc: BaseException, **payload: Any) -> None:
        """Emit a structured bus error message through the error callback.

        When no error callback is registered, the exception is logged locally.

        Args:
            error_type: Stable error category name for the emitted message.
            exc: Exception that triggered the error path.
            **payload: Additional error fields to include in the emitted
                message.

        Returns:
            None.
        """
        callback = self._error_callback
        if callback is None:
            log.exception("BusManager error without error callback", exc_info=exc)
            return

        message = {
            "error_type": error_type,
            "message": str(exc),
            "exception_type": exc.__class__.__name__,
            "traceback": "".join(traceback.format_exception(exc)).strip(),
            "wall_time": time.time(),
            **payload,
        }
        try:
            callback(message)
        except Exception:
            log.exception("Bus error callback failed")
