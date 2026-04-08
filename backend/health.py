from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Mapping

from historymanager import HistoryManager
from historymanager.manager import isoformat_z

from .state_store import StateStore

log = logging.getLogger(__name__)


class HealthPublisher:
    """Record backend lifecycle and summarized health events into history."""

    def __init__(
        self,
        *,
        history_manager: HistoryManager,
        raw_mirror_callback: Callable[[str, Mapping[str, Any]], Mapping[str, Any] | None] | None = None,
    ) -> None:
        self.history_manager = history_manager
        self._raw_mirror_callback = raw_mirror_callback

    def set_raw_mirror_callback(
        self,
        callback: Callable[[str, Mapping[str, Any]], Mapping[str, Any] | None] | None,
    ) -> None:
        self._raw_mirror_callback = callback

    def record_system_event(
        self,
        event_type: str,
        *,
        severity: str = "info",
        **extra: Any,
    ) -> dict[str, Any]:
        event = {
            "event_kind": "system_event",
            "event_type": event_type,
            "severity": severity,
            "recorded_by": "backend",
            "wall_time": isoformat_z(),
            **extra,
        }

        if self.history_manager.is_running:
            # Record to the history manager's raw writer first so identity
            # fields (stream_seq, event_uid, canonical_hash) are materialized
            # from the single authoritative counter.  The raw event dict is
            # mutated in-place, so the structured copy inherits the same IDs.
            raw_event = dict(event)
            self.history_manager.record_raw_event("system_event", raw_event)

            raw_mirror = self._raw_mirror_callback
            if raw_mirror is not None:
                try:
                    raw_mirror("system_event", dict(raw_event))
                except Exception:
                    log.exception(
                        "Failed to mirror raw system_event to gateway: %s",
                        event_type,
                    )

            self.history_manager.record_structured_event(
                "system_event",
                {
                    **raw_event,
                    "structured_at": isoformat_z(),
                },
            )
            return dict(raw_event)

        return event



class BackendHealthMonitor:
    """Poll backend runtime health and publish summarized watchdog state."""

    def __init__(
        self,
        *,
        history_manager: HistoryManager,
        state_store: StateStore,
        health_publisher: HealthPublisher,
        poll_interval_s: float = 1.0,
        queue_warning_fraction: float = 0.80,
        gui_stale_after_s: float = 6.0,
    ) -> None:
        self.history_manager = history_manager
        self.state_store = state_store
        self.health_publisher = health_publisher
        self.poll_interval_s = max(0.25, float(poll_interval_s))
        self.queue_warning_fraction = min(0.99, max(0.10, float(queue_warning_fraction)))
        self.gui_stale_after_s = max(1.0, float(gui_stale_after_s))
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_writer_signatures: dict[str, tuple[Any, ...]] = {}
        self._last_bus_signature: tuple[Any, ...] | None = None
        self._last_script_signature: tuple[Any, ...] | None = None
        self._last_gui_signature: tuple[Any, ...] | None = None
        self._last_overall_signature: tuple[Any, ...] | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="backend-health-monitor",
                daemon=True,
            )
            self._thread.start()
        self.sample_once()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=self.poll_interval_s + 1.0)

    def sample_once(self) -> dict[str, Any]:
        snapshot = self._build_health_snapshot()
        self.state_store.set_health_snapshot(
            sampled_at=snapshot["sampled_at"],
            overall_status=snapshot["overall_status"],
            active_warnings=list(snapshot["active_warnings"]),
            writers=snapshot["writers"],
            bus=snapshot["bus"],
            script=snapshot["script"],
            gui=snapshot["gui"],
        )
        self._emit_transition_events(snapshot)
        return snapshot

    def _run(self) -> None:
        while not self._stop_event.wait(self.poll_interval_s):
            try:
                self.sample_once()
            except Exception:
                # Health monitoring must never take the backend down.
                pass

    def _build_health_snapshot(self) -> dict[str, Any]:
        sampled_at = isoformat_z()
        history_health = self.history_manager.get_health_snapshot()
        runtime_snapshot = self.state_store.get_snapshot()
        bus_state = runtime_snapshot.get("bus", {})
        script_state = runtime_snapshot.get("script_runner", {})
        gui_state = runtime_snapshot.get("gui", {})
        run_state = runtime_snapshot.get("run", {})
        writers = dict(history_health.get("writers", {}))

        active_warnings: list[str] = []
        overall_rank = 0  # 0=ok, 1=warning, 2=error

        normalized_writers: dict[str, dict[str, Any]] = {}
        for side_name in ("raw", "rawbak", "structured"):
            entry = dict(writers.get(side_name, {}))
            normalized = self._normalize_writer_health(side_name, entry)
            normalized_writers[side_name] = normalized
            status = normalized.get("status", "unknown")
            if status == "error":
                overall_rank = max(overall_rank, 2)
                active_warnings.append(f"{side_name} writer unhealthy")
            elif status == "warning":
                overall_rank = max(overall_rank, 1)
                active_warnings.append(f"{side_name} writer degraded")
            queue_warning = normalized.get("queue_warning")
            if isinstance(queue_warning, str) and queue_warning:
                active_warnings.append(queue_warning)
                overall_rank = max(overall_rank, 1)

        bus_health = self._normalize_bus_health(
            bus_state,
            run_is_active=bool(run_state.get("is_running")),
        )
        if bus_health["status"] == "error":
            overall_rank = max(overall_rank, 2)
            active_warnings.append("bus disconnected")
        elif bus_health["status"] == "warning":
            overall_rank = max(overall_rank, 1)
            if bus_health.get("reconnecting"):
                active_warnings.append("bus reconnecting")
            else:
                active_warnings.append("bus not connected")

        script_health = self._normalize_script_health(script_state)
        if script_health["status"] == "warning":
            overall_rank = max(overall_rank, 1)
            active_warnings.append("script runner state inconsistent")

        gui_health = self._normalize_gui_health(
            gui_state,
            run_is_active=bool(run_state.get("is_running")),
            run_mode=str(run_state.get("mode") or ""),
        )
        if gui_health["status"] == "error":
            overall_rank = max(overall_rank, 2)
        elif gui_health["status"] == "warning":
            overall_rank = max(overall_rank, 1)
        active_warnings.extend(list(gui_health.get("warnings", [])))

        # De-duplicate while preserving order.
        deduped_warnings = list(dict.fromkeys(active_warnings))
        overall_status = {0: "ok", 1: "warning", 2: "error"}[overall_rank]
        return {
            "sampled_at": sampled_at,
            "overall_status": overall_status,
            "active_warnings": deduped_warnings,
            "writers": normalized_writers,
            "bus": bus_health,
            "script": script_health,
            "gui": gui_health,
            "history_run_id": history_health.get("active_run_id"),
        }

    def _normalize_writer_health(self, side_name: str, entry: Mapping[str, Any]) -> dict[str, Any]:
        configured = bool(entry.get("configured"))
        process_alive = bool(entry.get("process_alive"))
        writer_status = str(entry.get("writer_status") or "unknown")
        queue_depth = entry.get("queue_depth")
        queue_limit = entry.get("queue_limit")
        dropped_events = int(entry.get("dropped_events") or 0)
        error_count = int(entry.get("error_count") or 0)
        utilization = None
        if isinstance(queue_depth, int) and isinstance(queue_limit, int) and queue_limit > 0:
            utilization = queue_depth / queue_limit

        queue_warning = None
        if utilization is not None and utilization >= self.queue_warning_fraction:
            queue_warning = f"{side_name} queue at {utilization * 100:.0f}% ({queue_depth}/{queue_limit})"

        if not configured:
            status = "idle"
        elif not process_alive:
            status = "error"
        elif writer_status in {"error", "terminated"}:
            status = "error"
        elif queue_warning is not None or dropped_events > 0 or error_count > 0:
            status = "warning"
        else:
            status = "ok"

        return {
            "side_name": side_name,
            "configured": configured,
            "process_alive": process_alive,
            "pid": entry.get("pid"),
            "writer_status": writer_status,
            "status": status,
            "queue_depth": queue_depth,
            "queue_limit": queue_limit,
            "queue_utilization": utilization,
            "queue_max_depth": entry.get("queue_max_depth"),
            "dropped_events": dropped_events,
            "error_count": error_count,
            "last_error_wall_time": entry.get("last_error_wall_time"),
            "last_flush_wall_time": entry.get("last_flush_wall_time"),
            "snapshots_written": entry.get("snapshots_written"),
            "stream_counts": dict(entry.get("stream_counts") or {}),
            "queue_warning": queue_warning,
        }

    def _normalize_bus_health(self, bus_state: Mapping[str, Any], *, run_is_active: bool) -> dict[str, Any]:
        connected = bool(bus_state.get("connected"))
        reconnecting = bool(bus_state.get("reconnecting"))
        if reconnecting:
            status = "warning"
        elif connected:
            status = "ok"
        elif run_is_active:
            status = "warning"
        else:
            status = "idle"
        return {
            "connected": connected,
            "reconnecting": reconnecting,
            "status": status,
            "last_transition_wall_time": bus_state.get("last_transition_wall_time"),
            "sender": bus_state.get("sender"),
            "bitrate": bus_state.get("bitrate"),
            "registered_count": bus_state.get("registered_count"),
            "skipped_count": bus_state.get("skipped_count"),
        }

    def _normalize_script_health(self, script_state: Mapping[str, Any]) -> dict[str, Any]:
        is_running = bool(script_state.get("is_running"))
        pid = script_state.get("pid")
        name = script_state.get("name")
        launch_mode = script_state.get("launch_mode")
        is_held = bool(script_state.get("is_held"))
        hold_requested = bool(script_state.get("hold_requested"))

        if is_running and not pid:
            status = "warning"
        elif is_running:
            status = "ok"
        else:
            status = "idle"

        return {
            "is_running": is_running,
            "pid": pid,
            "name": name,
            "launch_mode": launch_mode,
            "status": status,
            "is_held": is_held,
            "hold_requested": hold_requested,
            "started_wall_time": script_state.get("started_wall_time"),
            "finished_wall_time": script_state.get("finished_wall_time"),
            "last_exit_code": script_state.get("last_exit_code"),
            "last_stop_reason": script_state.get("last_stop_reason"),
        }

    def _normalize_gui_health(
        self,
        gui_state: Mapping[str, Any],
        *,
        run_is_active: bool,
        run_mode: str,
    ) -> dict[str, Any]:
        sessions_by_connection = gui_state.get("by_connection_id", {})
        if not isinstance(sessions_by_connection, Mapping):
            sessions_by_connection = {}

        sessions = []
        stale_sessions = []
        for connection_id, value in sessions_by_connection.items():
            if not isinstance(value, Mapping):
                continue
            entry = dict(value)
            entry.setdefault("connection_id", connection_id)
            age_seconds = entry.get("last_message_age_seconds")
            try:
                normalized_age = float(age_seconds) if age_seconds is not None else None
            except (TypeError, ValueError):
                normalized_age = None
            entry["last_message_age_seconds"] = normalized_age
            sessions.append(entry)
            if normalized_age is not None and normalized_age >= self.gui_stale_after_s:
                stale_sessions.append(entry)

        window_roles = sorted(
            {
                str(item.get("window_role"))
                for item in sessions
                if item.get("window_role") not in (None, "")
            }
        )
        expected_roles = ["live_controller", "live_scada"] if run_is_active and run_mode == "live" else []
        missing_roles = [role for role in expected_roles if role not in window_roles]

        warnings: list[str] = []
        if stale_sessions:
            warnings.append(f"{len(stale_sessions)} GUI window(s) stale")
        if missing_roles:
            warnings.append(f"missing GUI roles: {', '.join(missing_roles)}")

        if run_is_active and run_mode == "live" and not sessions:
            status = "error"
        elif missing_roles:
            status = "warning"
        elif stale_sessions:
            status = "warning"
        elif sessions:
            status = "ok"
        else:
            status = "idle"

        return {
            "status": status,
            "total_windows": len(sessions),
            "stale_window_count": len(stale_sessions),
            "stale_window_roles": [item.get("window_role") for item in stale_sessions if item.get("window_role")],
            "window_roles": window_roles,
            "expected_roles": expected_roles,
            "missing_roles": missing_roles,
            "warning_count": len(warnings),
            "warnings": warnings,
            "last_event_wall_time": gui_state.get("last_event_wall_time"),
        }

    def _emit_transition_events(self, snapshot: Mapping[str, Any]) -> None:
        writers = snapshot.get("writers", {})
        if isinstance(writers, Mapping):
            for side_name, entry in writers.items():
                if not isinstance(entry, Mapping):
                    continue
                signature = (
                    entry.get("status"),
                    entry.get("process_alive"),
                    entry.get("writer_status"),
                    entry.get("queue_depth"),
                    entry.get("dropped_events"),
                    entry.get("error_count"),
                )
                previous = self._last_writer_signatures.get(str(side_name))
                if previous != signature:
                    severity = "error" if entry.get("status") == "error" else ("warning" if entry.get("status") == "warning" else "info")
                    self.health_publisher.record_system_event(
                        "writer_health_changed",
                        severity=severity,
                        writer_side=str(side_name),
                        writer_health=dict(entry),
                    )
                    self._last_writer_signatures[str(side_name)] = signature

        bus = snapshot.get("bus", {})
        if isinstance(bus, Mapping):
            bus_signature = (
                bus.get("status"),
                bus.get("connected"),
                bus.get("reconnecting"),
                bus.get("sender"),
                bus.get("bitrate"),
            )
            if self._last_bus_signature != bus_signature:
                severity = "error" if bus.get("status") == "error" else ("warning" if bus.get("status") == "warning" else "info")
                self.health_publisher.record_system_event(
                    "bus_health_changed",
                    severity=severity,
                    bus_health=dict(bus),
                )
                self._last_bus_signature = bus_signature

        script = snapshot.get("script", {})
        if isinstance(script, Mapping):
            script_signature = (
                script.get("status"),
                script.get("is_running"),
                script.get("pid"),
                script.get("name"),
                script.get("last_exit_code"),
                script.get("last_stop_reason"),
                script.get("is_held"),
                script.get("hold_requested"),
            )
            if self._last_script_signature != script_signature:
                severity = "warning" if script.get("status") == "warning" else "info"
                self.health_publisher.record_system_event(
                    "script_health_changed",
                    severity=severity,
                    script_health=dict(script),
                )
                self._last_script_signature = script_signature

        gui = snapshot.get("gui", {})
        if isinstance(gui, Mapping):
            gui_signature = (
                gui.get("status"),
                gui.get("total_windows"),
                gui.get("stale_window_count"),
                tuple(gui.get("window_roles", [])),
                tuple(gui.get("missing_roles", [])),
            )
            if self._last_gui_signature != gui_signature:
                severity = "error" if gui.get("status") == "error" else ("warning" if gui.get("status") == "warning" else "info")
                self.health_publisher.record_system_event(
                    "gui_watchdog_health_changed",
                    severity=severity,
                    gui_health=dict(gui),
                )
                self._last_gui_signature = gui_signature

        overall_signature = (
            snapshot.get("overall_status"),
            tuple(snapshot.get("active_warnings", [])),
        )
        if self._last_overall_signature != overall_signature:
            severity = "error" if snapshot.get("overall_status") == "error" else ("warning" if snapshot.get("overall_status") == "warning" else "info")
            self.health_publisher.record_system_event(
                "backend_health_changed",
                severity=severity,
                overall_status=snapshot.get("overall_status"),
                active_warnings=list(snapshot.get("active_warnings", [])),
            )
            self._last_overall_signature = overall_signature
