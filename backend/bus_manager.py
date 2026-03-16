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
    sender: str
    bitrate: int
    registered_ids: list[str]
    skipped_ids: list[str]
    registered_count: int
    skipped_count: int


class BusManager:
    """Backend-owned bus lifecycle wrapper with reconnect supervision.

    This version keeps the public surface close to the current branch while
    adding the missing pieces needed for the first backend-first bus commit:

    - explicit lifecycle callbacks for service-side fanout hooks
    - optional packet hook attachment when the Bus implementation supports it
    - an optional receive loop when the Bus exposes a pull-style packet API
    - reconnect supervision with exponential backoff

    The manager is intentionally conservative:

    - it keeps the current initialize_live_hardware()/shutdown_live_hardware()
      entry points so the IPC handlers do not need a large rewrite
    - it avoids assuming too much about the Bus implementation
    - if the Bus already owns its own receive thread, this manager will not try
      to force a second packet path unless it finds a safe listener or receive
      method
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
        self.sender = sender if sender is not None else settings.sender
        self.bitrate = bitrate if bitrate is not None else settings.bitrate
        self.packetprinting = packetprinting
        self.packetlogging = packetlogging

        self.auto_reconnect = auto_reconnect
        self.reconnect_initial_delay = max(0.05, float(reconnect_initial_delay))
        self.reconnect_max_delay = max(self.reconnect_initial_delay, float(reconnect_max_delay))
        self.reconnect_backoff = max(1.10, float(reconnect_backoff))
        self.receive_poll_interval = max(0.01, float(receive_poll_interval))
        self.monitor_interval = max(0.05, float(monitor_interval))
        self.max_receive_failures_before_reconnect = max(1, int(max_receive_failures_before_reconnect))

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
        return self._bus

    @property
    def is_running(self) -> bool:
        return self._bus is not None and self._entered

    @property
    def last_init_result(self) -> BusInitResult | None:
        return self._last_init_result

    def set_event_callbacks(
        self,
        *,
        status_callback: BusStatusCallback | None = None,
        packet_callback: BusPacketCallback | None = None,
        error_callback: BusErrorCallback | None = None,
    ) -> None:
        self._status_callback = status_callback
        self._packet_callback = packet_callback
        self._error_callback = error_callback

    def initialize_live_hardware(self, registry: DeviceRegistry) -> BusInitResult:
        with self._lock:
            if self.is_running:
                raise RuntimeError("BusManager is already running")

            self._registry = registry
            self._manual_shutdown = False
            self._stop_event.clear()
            self._receive_stop_event.clear()

            result = self._open_bus_and_register(registry)
            self._start_supervisor_thread_locked()
            self._start_receive_loop_if_supported_locked()
            return result

    def shutdown_live_hardware(self) -> None:
        with self._lock:
            self._manual_shutdown = True
            self._stop_event.set()
            self._receive_stop_event.set()
            self._safe_shutdown_current_bus_locked(reason="manual_shutdown")

        self._join_background_threads()

    def _open_bus_and_register(self, registry: DeviceRegistry) -> BusInitResult:
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
                reason="initial_connect" if self._next_reconnect_not_before == 0.0 else "reconnect_success",
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
        if self._supervisor_thread is not None and self._supervisor_thread.is_alive():
            return

        self._supervisor_thread = threading.Thread(
            target=self._supervisor_loop,
            name="backend-bus-supervisor",
            daemon=True,
        )
        self._supervisor_thread.start()

    def _start_receive_loop_if_supported_locked(self) -> None:
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
                backoff = min(self.reconnect_max_delay, backoff * self.reconnect_backoff)

    def _resolve_receive_callable(self, bus: Bus | None) -> Callable[[], Any] | None:
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
                try:
                    return candidate(timeout=self.receive_poll_interval)
                except TypeError:
                    return candidate()

            return _call_candidate

        return None

    def _try_attach_packet_listener(self, bus: Bus) -> bool:
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
        callback = self._packet_callback
        if callback is None:
            return

        try:
            callback(packet)
        except Exception as exc:
            self._emit_error("bus_packet_callback_failed", exc)

    def _safe_shutdown_current_bus_locked(self, *, reason: str) -> None:
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
        receive_thread = self._receive_thread
        supervisor_thread = self._supervisor_thread

        if receive_thread is not None and receive_thread.is_alive():
            receive_thread.join(timeout=1.0)
        if supervisor_thread is not None and supervisor_thread.is_alive():
            supervisor_thread.join(timeout=1.0)

        self._receive_thread = None
        self._supervisor_thread = None

    def _emit_status(self, event: str, **payload: Any) -> None:
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
