from __future__ import annotations

import argparse
import hashlib
import base64
import json
import logging
from bisect import bisect_left, bisect_right
from copy import deepcopy
from functools import lru_cache
import os
import socket
import sys
from datetime import datetime, timedelta
from uuid import uuid4
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt5.QtCore import QObject, QTimer, Qt, QEvent, QRect  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox, QPushButton, QFrame, QLabel  # noqa: E402

import settings  # noqa: E402
from gui import QLoggingHandler  # noqa: E402
from gui.abort_relay import send_abort_request, send_clear_abort_latch_request  # noqa: E402
from gui.backend_client import BackendClient, GuiBackendActionAPI  # noqa: E402
from gui.controller_window import ControllerWindow  # noqa: E402
from gui.device_catalog import BackendDeviceCatalog  # noqa: E402
from gui.playback_state_manager import PlaybackStateManager, PlaybackRunContext  # noqa: E402
from gui.scada_window import ScadaWindow  # noqa: E402
from gui.workspace_metadata import attach_workspace_persistence, prepare_workspace_window  # noqa: E402
from historymanager.paths import HISTORY_ROOT_DIRNAME  # noqa: E402

log = logging.getLogger(__name__)

_PLAYBACK_SOURCE_NATIVE = "native"
_PLAYBACK_SOURCE_REBUILD = "rebuild"
_REBUILD_SELECTION_PREFIX = "rebuild::"


def _project_root() -> Path:
    return PROJECT_ROOT


def _decode_json_arg(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        raise ValueError(f"Failed to decode JSON argument: {exc}") from exc
    return None



def _supervisor_message_payload(
    *,
    message_type: str,
    mode: str,
    window_kind: str,
    window_role: str,
    session_id: str | None,
) -> dict[str, Any]:
    return {
        "type": message_type,
        "mode": mode,
        "window_kind": window_kind,
        "window_role": window_role,
        "session_id": session_id,
        "pid": os.getpid(),
        "wall_time": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
    }



def _coerce_health_warnings(value: Any) -> list[str]:
    warnings: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                warnings.append(item.strip())
            elif isinstance(item, dict):
                message = item.get("message") or item.get("warning") or item.get("detail")
                if isinstance(message, str) and message.strip():
                    warnings.append(message.strip())
    return warnings


def _normalize_health_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    summary = dict(payload or {})
    overall_status = str(summary.get("overall_status") or "unknown").strip().lower() or "unknown"
    active_warnings = _coerce_health_warnings(summary.get("active_warnings"))
    if not active_warnings:
        writer_section = summary.get("writers")
        if isinstance(writer_section, dict):
            for writer_name, writer_payload in writer_section.items():
                if not isinstance(writer_payload, dict):
                    continue
                writer_status = str(writer_payload.get("status") or "unknown").strip().lower()
                if writer_status not in {"ok", "healthy", "running", "idle"}:
                    active_warnings.append(f"{writer_name} writer: {writer_status}")
        bus_section = summary.get("bus")
        if isinstance(bus_section, dict):
            bus_status = str(bus_section.get("status") or "unknown").strip().lower()
            if bus_status not in {"ok", "healthy", "connected", "idle"}:
                active_warnings.append(f"bus: {bus_status}")
        script_section = summary.get("script")
        if isinstance(script_section, dict):
            script_status = str(script_section.get("status") or "unknown").strip().lower()
            if script_status not in {"ok", "healthy", "idle", "stopped"}:
                active_warnings.append(f"script: {script_status}")

    return {
        "sampled_at": summary.get("sampled_at"),
        "overall_status": overall_status,
        "active_warning_count": int(summary.get("active_warning_count") or len(active_warnings)),
        "active_warnings": active_warnings,
    }


class WindowHealthBannerController(QObject):
    _STYLE_BY_SEVERITY = {
        "warning": ("#f9a825", "#1f1f1f"),
        "error": ("#c62828", "#ffffff"),
    }

    def __init__(self, *, window: Any) -> None:
        super().__init__(window)
        self.window = window
        self.frame = QFrame(window)
        self.frame.setObjectName("windowHealthBanner")
        self.frame.hide()

        self.title_label = QLabel(self.frame)
        self.title_label.setText("")
        self.title_label.setWordWrap(False)
        self.title_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        self.detail_label = QLabel(self.frame)
        self.detail_label.setText("")
        self.detail_label.setWordWrap(True)
        self.detail_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        window.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.window and event.type() in (
            QEvent.Resize,
            QEvent.Show,
            QEvent.WindowStateChange,
            QEvent.Move,
        ):
            self.reposition()
        return False

    def clear(self) -> None:
        self.frame.hide()

    def show_backend_disconnected(self, *, reason_text: str | None) -> None:
        detail = reason_text or "The GUI window is disconnected from backend."
        self._show_banner(
            severity="error",
            title="BACKEND DISCONNECTED",
            detail=detail,
        )

    def show_backend_reconnecting(self, *, reason_text: str | None) -> None:
        detail = reason_text or "Trying to reconnect this GUI window to the backend."
        self._show_banner(
            severity="warning",
            title="BACKEND RECONNECTING",
            detail=detail,
        )

    def show_health_summary(self, summary: dict[str, Any]) -> None:
        normalized = _normalize_health_payload(summary)
        overall = normalized["overall_status"]
        warnings = normalized["active_warnings"]

        if overall in {"ok", "healthy", "idle"} and not warnings:
            self.clear()
            return

        severity = "error" if overall in {"error", "failed", "dead", "disconnected"} else "warning"
        title = "BACKEND DEGRADED" if severity == "error" else "BACKEND WARNING"
        detail = "; ".join(warnings[:3]) if warnings else f"overall_status={overall}"
        self._show_banner(
            severity=severity,
            title=title,
            detail=detail,
        )

    def show_backend_error(self, *, code: str | None, message: str | None) -> None:
        detail_parts = []
        if code:
            detail_parts.append(f"code={code}")
        if message:
            detail_parts.append(message)
        detail = " - ".join(detail_parts) if detail_parts else "Backend reported an error."
        self._show_banner(
            severity="error",
            title="BACKEND ERROR",
            detail=detail,
        )

    def _show_banner(self, *, severity: str, title: str, detail: str) -> None:
        border, fg = self._STYLE_BY_SEVERITY.get(severity, self._STYLE_BY_SEVERITY["warning"])
        self.frame.setStyleSheet(
            """
            QFrame#windowHealthBanner {
                background-color: rgba(18, 18, 18, 225);
                border: 2px solid BORDER_COLOR;
                border-radius: 10px;
            }
            """.replace("BORDER_COLOR", border)
        )
        self.title_label.setStyleSheet(
            f"color: {border}; font-size: 16px; font-weight: 700; background: transparent;"
        )
        self.detail_label.setStyleSheet(
            f"color: {fg}; font-size: 12px; background: transparent;"
        )
        self.title_label.setText(title)
        self.detail_label.setText(detail)
        self.frame.show()
        self.reposition()

    def reposition(self) -> None:
        if self.frame.isHidden():
            return

        margin = 14
        frame_width = max(320, self.window.width() - (margin * 2))
        title_height = 26
        detail_height = 40
        frame_height = title_height + detail_height + 18

        self.frame.setGeometry(QRect(margin, margin, frame_width, frame_height))
        self.title_label.setGeometry(14, 8, frame_width - 28, title_height)
        self.detail_label.setGeometry(14, 30, frame_width - 28, detail_height)
        self.frame.raise_()


class SupervisorHeartbeatClient(QObject):
    def __init__(
        self,
        *,
        socket_path: str | None,
        mode: str,
        window_kind: str,
        window_role: str,
        session_id: str | None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.socket_path = socket_path or ""
        self.mode = mode
        self.window_kind = window_kind
        self.window_role = window_role
        self.session_id = session_id
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.send_heartbeat)
        self._disabled = False

    def _is_dummy_socket(self) -> bool:
        if not self.socket_path:
            return True
        name = Path(self.socket_path).name
        return "mints_scada_supervisor_dummy" in self.socket_path or name.startswith("noop_supervisor_")

    def start(self) -> None:
        if not self.socket_path or self._is_dummy_socket():
            log.debug(
                "Supervisor heartbeat disabled for %s via dummy socket: %s",
                self.window_role,
                self.socket_path,
            )
            self._disabled = True
            return
        self._send("hello")
        if not self._disabled:
            self._timer.start()
            log.info(
                "Started supervisor heartbeat for %s via %s",
                self.window_role,
                self.socket_path,
            )

    def stop(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
        if self.socket_path and not self._disabled:
            self._send("goodbye")

    def send_heartbeat(self) -> None:
        if not self.socket_path or self._disabled:
            return
        self._send("heartbeat")

    def _send(self, message_type: str) -> None:
        if self._disabled:
            return
        payload = _supervisor_message_payload(
            message_type=message_type,
            mode=self.mode,
            window_kind=self.window_kind,
            window_role=self.window_role,
            session_id=self.session_id,
        )
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.connect(self.socket_path)
                wire = json.dumps(payload, ensure_ascii=False, sort_keys=False) + "\n"
                sock.sendall(wire.encode("utf-8"))
        except FileNotFoundError:
            self._disabled = True
            if self._timer.isActive():
                self._timer.stop()
            log.debug(
                "Supervisor heartbeat disabled for %s because socket disappeared: %s",
                self.window_role,
                self.socket_path,
            )
        except Exception as exc:
            log.debug(
                "Supervisor heartbeat send failed for %s (%s): %s",
                self.window_role,
                message_type,
                exc,
            )


class WindowHostFacade:
    def __init__(self, *, window_kind: str, window: Any) -> None:
        self.window_kind = window_kind
        self.window = window
        self.controller = window if window_kind == "controller" else None
        self.scada = window if window_kind == "scada" else None
        self.health_banner_controller = WindowHealthBannerController(window=window)
        self.playback_state: PlaybackStateManager | None = None

    @property
    def timeline(self):
        if self.controller is None:
            raise AttributeError("Timeline is only available for controller windows")
        return self.controller.timeline

    @property
    def playback_time(self) -> float:
        if self.playback_state is not None:
            return self.playback_state.position_seconds
        if self.controller is None:
            return 0.0
        return getattr(self.controller, "playback_time", 0.0)

    @playback_time.setter
    def playback_time(self, value: float) -> None:
        if self.playback_state is not None:
            self.playback_state.set_position(float(value))
            return
        if self.controller is not None:
            self.controller.playback_time = value

    def addDevice(self, *args: Any, **kwargs: Any) -> None:
        if self.controller is not None:
            self.controller.addDevice(*args, **kwargs)

    def handle_backend_status(self, payload: dict[str, Any]) -> None:
        handler = getattr(self.window, "handle_backend_status", None)
        if callable(handler):
            handler(dict(payload))

    def apply_backend_state_snapshot(self, payload: dict[str, Any]) -> None:
        handler = getattr(self.window, "apply_backend_state_snapshot", None)
        if callable(handler):
            handler(dict(payload))

    def handle_structured_event(self, payload: dict[str, Any]) -> None:
        handler = getattr(self.window, "handle_structured_event", None)
        if callable(handler):
            handler(dict(payload))

    def update_health_summary(self, summary: dict[str, Any]) -> None:
        setattr(self.window, "backend_health_summary", dict(summary))
        self.health_banner_controller.show_health_summary(dict(summary))

    def show_backend_disconnected(self, reason_payload: dict[str, Any] | None) -> None:
        detail = None
        if isinstance(reason_payload, dict):
            detail = reason_payload.get("message") or reason_payload.get("code")
        self.health_banner_controller.show_backend_disconnected(reason_text=detail)

    def show_backend_reconnecting(self, reason_payload: dict[str, Any] | None) -> None:
        detail = None
        if isinstance(reason_payload, dict):
            detail = reason_payload.get("message") or reason_payload.get("code")
            retry_in_ms = reason_payload.get("retry_in_ms")
            if isinstance(retry_in_ms, int) and retry_in_ms > 0:
                detail = f"{detail or 'Backend reconnect scheduled.'} Retrying in {retry_in_ms / 1000:.1f}s."
        self.health_banner_controller.show_backend_reconnecting(reason_text=detail)

    def show_backend_error_banner(self, payload: dict[str, Any]) -> None:
        self.health_banner_controller.show_backend_error(
            code=str(payload.get("code") or "") or None,
            message=str(payload.get("message") or "") or None,
        )


class GuiBackendBridge:
    """Bind backend IPC messages into a single GUI window process."""

    def __init__(
        self,
        *,
        window: Any,
        backend_client: BackendClient,
        mode: str,
        window_kind: str,
        initialize_live_hardware_on_connect: bool,
        pending_start_run_payload: dict[str, Any] | None = None,
    ) -> None:
        self.window = window
        self.backend_client = backend_client
        self.mode = str(mode)
        self.window_kind = str(window_kind)
        self.initialize_live_hardware_on_connect = initialize_live_hardware_on_connect
        self.pending_start_run_payload = dict(pending_start_run_payload or {}) or None
        log.info(
            "GuiBackendBridge init: window_kind=%s pending_start_run_payload=%s",
            self.window_kind,
            "present" if self.pending_start_run_payload else "None",
        )
        self.device_catalog = BackendDeviceCatalog()
        self._last_disconnect_reason: dict[str, Any] | None = None
        self._health_poll_timer = QTimer(self.window.window if hasattr(self.window, 'window') else None)
        self._health_poll_timer.setInterval(1000)
        self._health_poll_timer.timeout.connect(self._poll_backend_health)
        self._state_sync_timer = QTimer(self.window.window if hasattr(self.window, 'window') else None)
        self._state_sync_timer.setInterval(100 if self.mode == "live" else 5000)
        self._state_sync_timer.timeout.connect(self._sync_backend_runtime_state)
        self.gui_action_api = GuiBackendActionAPI(
            backend_client=self.backend_client,
            mode=self.mode,
            window_kind=self.window_kind,
            parent=self.window.window if hasattr(self.window, "window") else None,
        )

        self._attach_gui_action_api()
        self._connect_signals()

    def _attach_gui_action_api(self) -> None:
        targets = [self.window]
        for child_name in ("controller", "scada"):
            child = getattr(self.window, child_name, None)
            if child is not None:
                targets.append(child)

        for target in targets:
            setattr(target, "gui_action_api", self.gui_action_api)
            setattr(target, "backend_device_catalog", self.device_catalog)
            setattr(target, "send_operator_action", self.send_operator_action)
            setattr(target, "request_backend_command", self.request_backend_command)
            setattr(target, "start_backend_script", self.start_backend_script)
            setattr(target, "stop_backend_script", self.stop_backend_script)
            setattr(target, "hold_backend_script", self.hold_backend_script)
            setattr(target, "continue_backend_script", self.continue_backend_script)
            setattr(target, "request_backend_status_now", self.request_backend_status_now)
            setattr(target, "request_full_backend_state", self.request_full_backend_state)
            setattr(target, "start_backend_run", self.start_backend_run)
            setattr(target, "finish_backend_run", self.finish_backend_run)
            setattr(target, "backend_runtime_owner", "backend_service")
            setattr(target, "backend_control_mode", "backend_first")
            setattr(target, "backend_direct_client_exposed", False)

    def _connect_signals(self) -> None:
        self.backend_client.connected.connect(self.on_connected)
        self.backend_client.disconnected.connect(self.on_disconnected)
        self.backend_client.disconnected_with_reason.connect(self.on_disconnected_with_reason)
        if hasattr(self.backend_client, "reconnect_scheduled"):
            self.backend_client.reconnect_scheduled.connect(self.on_reconnect_scheduled)
        if hasattr(self.backend_client, "reconnect_attempt_started"):
            self.backend_client.reconnect_attempt_started.connect(self.on_reconnect_attempt_started)
        if hasattr(self.backend_client, "reconnect_succeeded"):
            self.backend_client.reconnect_succeeded.connect(self.on_reconnect_succeeded)
        self.backend_client.hello_ack_received.connect(self.on_hello_ack)
        self.backend_client.backend_status_received.connect(self.on_backend_status)
        self.backend_client.state_snapshot_received.connect(self.on_state_snapshot)
        self.backend_client.structured_event_received.connect(self.on_structured_event)
        self.backend_client.device_inventory_received.connect(self.on_device_inventory)
        self.backend_client.hardware_status_received.connect(self.on_hardware_status)
        self.backend_client.run_status_received.connect(self.on_run_status)
        self.backend_client.operator_action_recorded_received.connect(self.on_operator_action_recorded)
        self.backend_client.command_result_received.connect(self.on_command_result)
        self.backend_client.script_status_received.connect(self.on_script_status)
        self.backend_client.error_received.connect(self.on_error)

    def _poll_backend_health(self) -> None:
        if not self.backend_client.is_connected:
            return
        try:
            self.gui_action_api.request_backend_status()
        except Exception as exc:
            log.debug("Failed to request backend status for health polling: %s", exc)

    def _sync_backend_runtime_state(self) -> None:
        if not self.backend_client.is_connected:
            return
        try:
            self.gui_action_api.request_full_state()
        except Exception as exc:
            log.debug("Failed to refresh backend runtime state: %s", exc)

    def request_backend_status_now(self) -> None:
        self.gui_action_api.request_backend_status()

    def request_full_backend_state(self) -> None:
        self.gui_action_api.request_full_state()

    def start_backend_run(self) -> None:
        payload = self.pending_start_run_payload
        if payload is None:
            raise RuntimeError("No checklist metadata available for start_run")
        self.gui_action_api.start_run(payload)
        log.info("Requested backend start_run with checklist metadata: %s", payload)

    def finish_backend_run(self, *, reason: str = "operator_stop") -> None:
        self.gui_action_api.finish_run(reason=reason)

    def send_operator_action(self, action: str, **extra: Any) -> None:
        self.gui_action_api.record_operator_action(action, **extra)

    def request_backend_command(
        self,
        command_name: str,
        *,
        device_id: str | None = None,
        command_args: list[Any] | None = None,
        command_kwargs: dict[str, Any] | None = None,
        mock_only: bool = False,
        operator_action: dict[str, Any] | None = None,
    ) -> None:
        self.gui_action_api.request_backend_command(
            command_name,
            device_id=device_id,
            command_args=command_args,
            command_kwargs=command_kwargs,
            mock_only=mock_only,
            operator_action=operator_action,
        )

    def start_backend_script(
        self,
        *,
        name: str,
        command: list[str] | None = None,
        inline_python: str | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.gui_action_api.start_backend_script(
            name=name,
            command=command,
            inline_python=inline_python,
            cwd=cwd,
            env=env,
        )

    def stop_backend_script(self, *, reason: str = "operator_stop") -> None:
        self.gui_action_api.stop_backend_script(reason=reason)

    def hold_backend_script(self, *, reason: str = "operator_hold") -> None:
        self.gui_action_api.hold_backend_script(reason=reason)

    def continue_backend_script(self, *, reason: str = "operator_continue") -> None:
        self.gui_action_api.continue_backend_script(reason=reason)

    def on_connected(self) -> None:
        log.info("Connected to backend at %s", self.backend_client.socket_path)
        self._last_disconnect_reason = None
        setattr(self.window, "backend_reconnect_state", {"state": "connected"})
        if hasattr(self.window, "health_banner_controller"):
            self.window.health_banner_controller.clear()
        self.gui_action_api.refresh_runtime_views()
        self._poll_backend_health()
        if not self._health_poll_timer.isActive():
            self._health_poll_timer.start()
        if not self._state_sync_timer.isActive():
            self._state_sync_timer.start()

        if self.initialize_live_hardware_on_connect:
            try:
                self.gui_action_api.initialize_live_hardware()
            except Exception as exc:
                log.error("Failed to request live hardware initialization: %s", exc)

    def on_disconnected(self) -> None:
        log.warning("Disconnected from backend")
        setattr(self.window, "backend_connected", False)
        setattr(self.window, "backend_reconnect_state", {"state": "disconnected"})
        if self._health_poll_timer.isActive():
            self._health_poll_timer.stop()
        if self._state_sync_timer.isActive():
            self._state_sync_timer.stop()
        if hasattr(self.window, "show_backend_disconnected"):
            self.window.show_backend_disconnected(self._last_disconnect_reason)

    def on_disconnected_with_reason(self, payload: dict[str, Any]) -> None:
        self._last_disconnect_reason = dict(payload)
        setattr(self.window, "backend_disconnect_reason", dict(payload))

    def on_reconnect_scheduled(self, payload: dict[str, Any]) -> None:
        setattr(self.window, "backend_reconnect_state", {"state": "scheduled", **dict(payload)})
        if hasattr(self.window, "show_backend_reconnecting"):
            self.window.show_backend_reconnecting(dict(payload))

    def on_reconnect_attempt_started(self, payload: dict[str, Any]) -> None:
        setattr(self.window, "backend_reconnect_state", {"state": "attempting", **dict(payload)})
        if hasattr(self.window, "show_backend_reconnecting"):
            self.window.show_backend_reconnecting(dict(payload))

    def on_reconnect_succeeded(self, payload: dict[str, Any]) -> None:
        setattr(self.window, "backend_reconnect_state", {"state": "reconnected", **dict(payload)})
        setattr(self.window, "backend_disconnect_reason", None)
        if hasattr(self.window, "health_banner_controller"):
            self.window.health_banner_controller.clear()
        try:
            self.gui_action_api.refresh_runtime_views()
        except Exception as exc:
            log.debug("Failed to refresh backend runtime state after reconnect: %s", exc)

    def on_hello_ack(self, payload: dict[str, Any]) -> None:
        log.info(
            "Backend hello_ack: service=%s clients=%s",
            payload.get("service_name"),
            payload.get("connected_clients"),
        )
        setattr(self.window, "backend_connected", True)
        setattr(self.window, "backend_hello_ack", dict(payload))
        setattr(self.window, "backend_reconnect_state", {"state": "hello_ack", **dict(payload)})

        try:
            self.gui_action_api.refresh_runtime_views()
        except Exception as exc:
            log.debug("Failed to refresh backend state after hello_ack: %s", exc)

        if self.pending_start_run_payload is not None:
            log.info("Checklist metadata cached for manual Start Recording: %s", self.pending_start_run_payload)

    def on_backend_status(self, payload: dict[str, Any]) -> None:
        setattr(self.window, "backend_status", dict(payload))
        health_summary = payload.get("health_summary")
        if isinstance(health_summary, dict) and hasattr(self.window, "update_health_summary"):
            self.window.update_health_summary(dict(health_summary))
        handler = getattr(self.window, "handle_backend_status", None)
        if callable(handler):
            handler(dict(payload))

    def on_state_snapshot(self, snapshot: dict[str, Any]) -> None:
        # Seed device library from snapshot before applying runtime state.
        # Ensures devices appear in live mode without waiting for a separate
        # device_inventory event or hardware response.
        device_registry = snapshot.get("device_registry")
        if isinstance(device_registry, dict):
            devices = device_registry.get("devices", [])
            if isinstance(devices, list) and devices:
                new_proxies = self.device_catalog.sync_inventory(devices)
                for proxy in new_proxies:
                    try:
                        self.window.addDevice(proxy, proxy.meta)
                    except Exception as exc:
                        log.exception(
                            "Failed to add device proxy %s from snapshot: %s",
                            proxy.device_id, exc,
                        )

        self.device_catalog.apply_state_snapshot(snapshot)
        setattr(self.window, "backend_state_snapshot", dict(snapshot))
        setattr(self.window, "backend_device_presentation", self.device_catalog.to_presentation_snapshot())
        health_snapshot = snapshot.get("health")
        if isinstance(health_snapshot, dict) and hasattr(self.window, "update_health_summary"):
            self.window.update_health_summary(dict(health_snapshot))

        handler = getattr(self.window, "apply_backend_state_snapshot", None)
        if callable(handler):
            handler(dict(snapshot))

        for child_name in ("controller", "scada"):
            child = getattr(self.window, child_name, None)
            if child is not None:
                child_handler = getattr(child, "apply_backend_state_snapshot", None)
                if callable(child_handler):
                    child_handler(dict(snapshot))

    def on_structured_event(self, payload: dict[str, Any]) -> None:
        setattr(self.window, "last_structured_event", dict(payload))
        handler = getattr(self.window, "handle_structured_event", None)
        if callable(handler):
            handler(dict(payload))

        for child_name in ("controller", "scada"):
            child = getattr(self.window, child_name, None)
            if child is not None:
                child_handler = getattr(child, "handle_structured_event", None)
                if callable(child_handler):
                    child_handler(dict(payload))

    def on_device_inventory(self, payload: dict[str, Any]) -> None:
        devices = payload.get("devices", [])
        if not isinstance(devices, list):
            devices = []

        new_proxies = self.device_catalog.sync_inventory(devices)
        for proxy in new_proxies:
            try:
                self.window.addDevice(proxy, proxy.meta)
            except Exception as exc:
                log.exception("Failed to add backend device proxy %s: %s", proxy.device_id, exc)

        setattr(self.window, "backend_device_inventory", dict(payload))
        setattr(self.window, "backend_device_presentation", self.device_catalog.to_presentation_snapshot())

    def on_hardware_status(self, payload: dict[str, Any]) -> None:
        setattr(self.window, "backend_hardware_status", dict(payload))
        handler = getattr(self.window, "handle_hardware_status", None)
        if callable(handler):
            handler(dict(payload))

    def on_run_status(self, payload: dict[str, Any]) -> None:
        setattr(self.window, "backend_run_status", dict(payload))
        handler = getattr(self.window, "handle_run_status", None)
        if callable(handler):
            handler(dict(payload))

        status = str(payload.get("status") or "").strip().lower()
        if status in {"running", "finished", "completed", "stopped"}:
            try:
                self.gui_action_api.refresh_runtime_views()
            except Exception as exc:
                log.debug("Failed to refresh backend runtime state after run_status: %s", exc)

    def on_operator_action_recorded(self, payload: dict[str, Any]) -> None:
        setattr(self.window, "last_operator_action_recorded", dict(payload))
        handler = getattr(self.window, "handle_operator_action_recorded", None)
        if callable(handler):
            handler(dict(payload))

    def on_command_result(self, payload: dict[str, Any]) -> None:
        setattr(self.window, "last_command_result", dict(payload))
        handler = getattr(self.window, "handle_command_result", None)
        if callable(handler):
            handler(dict(payload))

    def on_script_status(self, payload: dict[str, Any]) -> None:
        setattr(self.window, "backend_script_status", dict(payload))
        handler = getattr(self.window, "handle_script_status", None)
        if callable(handler):
            handler(dict(payload))

    def on_error(self, payload: dict[str, Any]) -> None:
        code = payload.get("code", "backend_error")
        message = payload.get("message", "Unknown backend error")
        log.error("Backend error [%s]: %s", code, message)
        setattr(self.window, "backend_last_error", dict(payload))
        if hasattr(self.window, "show_backend_error_banner"):
            self.window.show_backend_error_banner(dict(payload))


def _load_json_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _load_jsonl_file(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception as exc:
                raise ValueError(f"Failed to parse JSONL line {line_number} in {path}: {exc}") from exc
            if isinstance(payload, dict):
                events.append(payload)
    return events


def _parse_iso_wall_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _extract_event_wall_time(event: dict[str, Any]) -> datetime | None:
    for key in ("recorded_at", "structured_at", "time", "runtime_time"):
        parsed = _parse_iso_wall_time(event.get(key))
        if parsed is not None:
            return parsed
    return None


def _build_playback_timeline_label(event: dict[str, Any]) -> str | None:
    stream = event.get("stream")
    if stream == "system_event":
        kind = event.get("event") or event.get("event_kind") or "system"
        return f"SYS {kind}"
    if stream == "operator_action":
        action = event.get("action") or event.get("event_kind") or "action"
        return f"OP {action}"
    if stream == "command_out":
        command_name = event.get("command_name") or event.get("event_kind") or "command"
        return f"CMD {command_name}"
    return None


def _parse_playback_selection(selected_test: str) -> tuple[str, str]:
    if isinstance(selected_test, str) and selected_test.startswith(_REBUILD_SELECTION_PREFIX):
        return selected_test[len(_REBUILD_SELECTION_PREFIX):], _PLAYBACK_SOURCE_REBUILD
    return selected_test, _PLAYBACK_SOURCE_NATIVE


def _playback_artifact_paths(run_dir: Path, playback_source: str) -> tuple[Path, Path]:
    if playback_source == _PLAYBACK_SOURCE_REBUILD:
        return run_dir / "merged.rebuild.jsonl", run_dir / "snapshots_rebuild"
    return run_dir / "merged.jsonl", run_dir / "snapshots"


def _resolve_ignitionhistory_run_dir(selected_test: str) -> Path:
    candidate = Path(selected_test)

    if candidate.is_absolute():
        if candidate.is_file() and candidate.name == "metadata.json":
            return candidate.parent
        if candidate.is_dir():
            return candidate
        raise FileNotFoundError(f"Playback path does not exist: {candidate}")

    if candidate.exists():
        resolved = candidate.resolve()
        if resolved.is_file() and resolved.name == "metadata.json":
            return resolved.parent
        if resolved.is_dir():
            return resolved

    history_root = _project_root() / HISTORY_ROOT_DIRNAME
    exact = history_root / selected_test
    if exact.is_dir():
        return exact

    raise FileNotFoundError(
        f"Could not resolve playback run '{selected_test}' under {history_root}"
    )


def _load_playback_device_proxies(window: Any) -> None:
    catalog = BackendDeviceCatalog()
    proxies = catalog.seed_from_settings_devices(settings.devices)

    setattr(window, "backend_device_catalog", catalog)
    setattr(window, "backend_device_presentation", catalog.to_presentation_snapshot())

    for proxy in proxies:
        window.addDevice(proxy, proxy.meta)


def _dispatch_playback_loaded(window: Any, payload: dict[str, Any]) -> None:
    setattr(window, "playback_load_summary", dict(payload))
    targets = [window]
    for child_name in ("controller", "scada", "script"):
        child = getattr(window, child_name, None)
        if child is not None:
            targets.append(child)
    for target in targets:
        handler = getattr(target, "handle_playback_loaded", None)
        if callable(handler):
            handler(dict(payload))


def _dispatch_playback_seek_bootstrap(window: Any, payload: dict[str, Any]) -> None:
    setattr(window, "playback_seek_summary", dict(payload))
    targets = [window]
    for child_name in ("controller", "scada", "script"):
        child = getattr(window, child_name, None)
        if child is not None:
            targets.append(child)
    for target in targets:
        handler = getattr(target, "handle_playback_seek_bootstrap", None)
        if callable(handler):
            handler(dict(payload))


def _build_playback_snapshot_index(
    *,
    snapshot_files: list[Path],
    start_dt: datetime | None,
) -> list[dict[str, Any]]:
    index_entries: list[dict[str, Any]] = []
    for path in snapshot_files:
        try:
            payload = _load_json_file(path)
        except Exception as exc:
            log.warning("Failed to parse playback snapshot %s: %s", path, exc)
            continue

        snapshot_dt = _parse_iso_wall_time(payload.get("recorded_at"))
        snapshot_index = payload.get("snapshot_index")
        if not isinstance(snapshot_index, int):
            try:
                snapshot_index = int(path.stem)
            except ValueError:
                snapshot_index = 0

        if snapshot_dt is not None and start_dt is not None:
            relative_seconds = max(0.0, (snapshot_dt - start_dt).total_seconds())
        else:
            relative_seconds = float(max(0, snapshot_index))

        index_entries.append(
            {
                "path": str(path),
                "snapshot_index": snapshot_index,
                "recorded_at": payload.get("recorded_at"),
                "relative_seconds": relative_seconds,
                "has_state": isinstance(payload.get("state"), dict),
            }
        )

    index_entries.sort(key=lambda entry: (entry["relative_seconds"], entry["snapshot_index"]))
    return index_entries


@lru_cache(maxsize=16)
def _load_playback_snapshot_payload_cached(snapshot_path: str) -> dict[str, Any]:
    return _load_json_file(Path(snapshot_path))


def _load_playback_snapshot_payload(snapshot_path: str) -> dict[str, Any]:
    return deepcopy(_load_playback_snapshot_payload_cached(snapshot_path))


def _datetime_to_seek_key(value: datetime | None) -> float | None:
    if not isinstance(value, datetime):
        return None
    return value.timestamp()


def _playback_event_end_index(
    *,
    event_time_keys: list[float] | None,
    seek_dt: datetime | None,
) -> int:
    if not event_time_keys:
        return 0
    seek_key = _datetime_to_seek_key(seek_dt)
    if seek_key is None:
        return 0
    return bisect_right(event_time_keys, seek_key)


def _apply_playback_state_snapshot(window: Any, snapshot_payload: dict[str, Any]) -> bool:
    snapshot_state = snapshot_payload.get("state")
    if not isinstance(snapshot_state, dict):
        if isinstance(snapshot_payload, dict) and any(
            key in snapshot_payload
            for key in ("device_states", "playback_clock", "mission_clock", "recording_clock", "run")
        ):
            snapshot_state = dict(snapshot_payload)
        else:
            return False

    catalog = getattr(window, "backend_device_catalog", None)
    if catalog is None:
        return False

    catalog.apply_state_snapshot(snapshot_state)
    setattr(window, "backend_device_presentation", catalog.to_presentation_snapshot())
    setattr(window, "playback_active_snapshot", dict(snapshot_payload))

    targets = [window]
    for child_name in ("controller", "scada"):
        child = getattr(window, child_name, None)
        if child is not None:
            targets.append(child)

    for target in targets:
        handler = getattr(target, "apply_backend_state_snapshot", None)
        if callable(handler):
            handler(dict(snapshot_state))

    return True


def _slice_playback_tail_events(
    merged_events: list[dict[str, Any]],
    *,
    replay_start_dt: datetime | None,
    seek_dt: datetime | None,
    event_time_keys: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Return events strictly after replay_start_dt and up to (inclusive) seek_dt.

    Boundary semantics: a snapshot represents state that already includes all
    effects up to and including its recorded_at.  Tail replay therefore starts
    *strictly after* the snapshot boundary to avoid double-applying events that
    were already captured by the snapshot.
    """
    if replay_start_dt is None or seek_dt is None:
        return []

    if event_time_keys and len(event_time_keys) == len(merged_events):
        start_key = _datetime_to_seek_key(replay_start_dt)
        end_key = _datetime_to_seek_key(seek_dt)
        if start_key is not None and end_key is not None:
            # bisect_right for start to first index strictly after snapshot boundary
            # bisect_right for end   to includes events at exactly seek target
            start_index = bisect_right(event_time_keys, start_key)
            end_index = bisect_right(event_time_keys, end_key)
            return list(merged_events[start_index:end_index])

    # Fallback linear scan - same boundary semantics as the bisect path.
    # Untimestamped events (event_dt is None) are skipped here; they are
    # handled via timestamp approximation in the seek-index build step
    # (_load_ignitionhistory_playback) so they appear in the fast bisect
    # path with their best-effort timestamp.
    tail_events: list[dict[str, Any]] = []
    for event in merged_events:
        event_dt = _extract_event_wall_time(event)
        if event_dt is None:
            continue
        if event_dt <= replay_start_dt:
            continue
        if event_dt > seek_dt:
            continue
        tail_events.append(event)
    return tail_events


def _find_nearest_snapshot_entry(snapshot_index: list[dict[str, Any]], seek_time: float) -> dict[str, Any] | None:
    if not snapshot_index:
        return None

    best_entry: dict[str, Any] | None = None
    for entry in snapshot_index:
        if entry["relative_seconds"] <= seek_time:
            best_entry = entry
        else:
            break

    if best_entry is not None:
        return best_entry
    return snapshot_index[0]


def _handle_playback_seek(window: Any, seek_time: float) -> None:
    psm = getattr(window, "playback_state", None)
    if psm is not None and psm.context is not None:
        snapshot_index = psm.snapshot_index
        merged_events = psm.seek_events
        event_time_keys = psm.event_time_keys
        start_dt = psm.start_dt
    else:
        snapshot_index = getattr(window, "playback_snapshot_index", [])
        merged_events = getattr(window, "playback_seek_events", getattr(window, "playback_merged_events", []))
        event_time_keys = getattr(window, "playback_event_time_keys", None)
        start_dt = getattr(window, "playback_start_dt", None)

    seek_time = max(0.0, float(seek_time))

    # Legacy mode: set position early so intermediate reads get the target value.
    # With a manager, psm.update_after_seek() handles this authoritatively later
    # and _apply_exact_playback_seek_state fans out to UI consumers.
    if psm is None:
        try:
            setattr(window, "playback_time", seek_time)
        except Exception:
            pass

    seek_dt = None
    if isinstance(start_dt, datetime):
        seek_dt = start_dt + timedelta(seconds=seek_time)

    selected_snapshot = _find_nearest_snapshot_entry(snapshot_index, seek_time)
    replay_start_dt = start_dt
    restored_from_snapshot = False

    if selected_snapshot is not None:
        try:
            snapshot_payload = _load_playback_snapshot_payload(selected_snapshot["path"])

            # Keep the snapshot bootstrap, but rewrite its playback clock to the exact
            # seek target so controller/SCADA do not snap back to the snapshot boundary
            # (0s / 5s / 10s / 15s / 20s) on mouse release.
            snapshot_state = snapshot_payload.get("state")
            if isinstance(snapshot_state, dict):
                updated_state = dict(snapshot_state)
                playback_clock = updated_state.get("playback_clock")
                if isinstance(playback_clock, dict):
                    playback_clock = dict(playback_clock)
                else:
                    playback_clock = {}
                playback_clock["position_seconds"] = seek_time
                total_duration = psm.duration_seconds if psm else getattr(window, "playback_duration_seconds", None)
                if isinstance(total_duration, (int, float)):
                    playback_clock.setdefault("total_duration_seconds", float(total_duration))
                updated_state["playback_clock"] = playback_clock
                snapshot_payload = dict(snapshot_payload)
                snapshot_payload["state"] = updated_state

            restored_from_snapshot = _apply_playback_state_snapshot(window, snapshot_payload)
            snapshot_recorded_at = _parse_iso_wall_time(snapshot_payload.get("recorded_at"))
            if snapshot_recorded_at is not None:
                replay_start_dt = snapshot_recorded_at
            elif isinstance(start_dt, datetime):
                replay_start_dt = start_dt + timedelta(seconds=float(selected_snapshot["relative_seconds"]))
        except Exception as exc:
            log.warning("Failed to restore playback snapshot during seek from %s: %s", selected_snapshot["path"], exc)

    tail_events = _slice_playback_tail_events(
        merged_events,
        replay_start_dt=replay_start_dt,
        seek_dt=seek_dt,
        event_time_keys=event_time_keys,
    )
    end_event_index = _playback_event_end_index(
        event_time_keys=event_time_keys,
        seek_dt=seek_dt,
    )

    if psm is not None:
        psm.update_after_seek(position=seek_time, event_index=end_event_index)

    payload = {
        "seek_time_seconds": seek_time,
        "selected_snapshot": dict(selected_snapshot) if selected_snapshot is not None else None,
        "restored_from_snapshot": restored_from_snapshot,
        "tail_event_count": len(tail_events),
        "replay_start_recorded_at": replay_start_dt.isoformat() if isinstance(replay_start_dt, datetime) else None,
        "seek_recorded_at": seek_dt.isoformat() if isinstance(seek_dt, datetime) else None,
    }
    setattr(window, "playback_seek_tail_events", tail_events)
    setattr(window, "playback_last_applied_time", seek_time)
    setattr(window, "playback_last_event_index", end_event_index)
    _dispatch_playback_seek_bootstrap(window, payload)

    for event in tail_events:
        handler = getattr(window, "handle_structured_event", None)
        if callable(handler):
            handler(dict(event))

    _apply_exact_playback_seek_state(window, seek_time)
    _update_reconstructed_playback_state(
        window,
        seek_time,
        tail_event_count=len(tail_events),
        restored_from_snapshot=restored_from_snapshot,
    )

    if selected_snapshot is not None:
        log.info(
            "Playback seek %.3fs bootstrapped from snapshot %s with %s tail events",
            seek_time,
            selected_snapshot.get("path"),
            len(tail_events),
        )
    else:
        log.info(
            "Playback seek %.3fs has no snapshot bootstrap; tail events=%s",
            seek_time,
            len(tail_events),
        )


def _resolve_applied_snapshot_state(window: Any) -> dict[str, Any]:
    """Return the unwrapped state dict that was actually applied to the UI.

    Prefers the controller's ``_last_backend_snapshot`` because that is the
    unwrapped, clock-corrected dict that ``apply_backend_state_snapshot``
    received and that the controller's display helpers read from.

    Falls back to re-parsing ``playback_active_snapshot`` (the raw snapshot
    payload on the facade) only when no controller is present (e.g. in a
    standalone SCADA window process).
    """
    # Primary: controller's post-apply container
    controller = getattr(window, "controller", None)
    if controller is not None:
        ctrl_snapshot = getattr(controller, "_last_backend_snapshot", None)
        if isinstance(ctrl_snapshot, dict):
            return ctrl_snapshot

    # Fallback: facade's raw snapshot payload (needs state-key unwrapping)
    snapshot_raw = getattr(window, "playback_active_snapshot", None) or {}
    snapshot_state = snapshot_raw.get("state", snapshot_raw)
    if isinstance(snapshot_state, dict):
        return snapshot_state
    return {}


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _build_reconstructed_playback_state(
    window: Any,
    seek_time: float,
    *,
    tail_event_count: int = 0,
    restored_from_snapshot: bool = False,
) -> dict[str, Any]:
    """Build a single dict representing playback-visible state at *seek_time*.

    Reads from the controller's post-apply state containers when available
    (these are the unwrapped, clock-corrected values that the controller
    actually uses for its displays).  Falls back to parsing the facade's
    raw ``playback_active_snapshot`` for non-controller window processes.

    This does NOT re-derive state -- it reads from sources that have already
    been updated by the seek/advance handler.
    """
    psm = getattr(window, "playback_state", None)

    # -- position / clock (PSM is always authoritative) --
    position = max(0.0, float(seek_time))
    duration = psm.duration_seconds if psm else 0.0
    wall_dt = psm.wall_time_for_position(position) if psm else None
    wall_iso = wall_dt.isoformat() if wall_dt is not None else None
    run_id = psm.run_id if psm else None

    # -- post-apply state sections --
    # _resolve_applied_snapshot_state prefers the controller's
    # _last_backend_snapshot (unwrapped, clock-corrected) over
    # the facade's raw playback_active_snapshot.
    applied = _resolve_applied_snapshot_state(window)

    # Prefer controller's individually-processed clock containers when
    # they exist -- these are extracted by apply_backend_state_snapshot
    # and are what the controller's display timer actually reads.
    controller = getattr(window, "controller", None)

    ctrl_mission = getattr(controller, "_backend_mission_clock", None) if controller else None
    ctrl_recording = getattr(controller, "_backend_recording_clock", None) if controller else None

    run_section = _safe_dict(applied.get("run"))
    script_section = _safe_dict(applied.get("script_runner"))
    alarms_section = _safe_dict(applied.get("alarms"))
    mission_clock = _safe_dict(ctrl_mission) if ctrl_mission is not None else _safe_dict(applied.get("mission_clock"))
    recording_clock = _safe_dict(ctrl_recording) if ctrl_recording is not None else _safe_dict(applied.get("recording_clock"))

    # -- device count from catalog (already updated by snapshot apply) --
    catalog = getattr(window, "backend_device_catalog", None)
    device_count = len(catalog) if catalog is not None else 0

    return {
        # Position
        "position_seconds": position,
        "duration_seconds": duration,
        "wall_time_iso": wall_iso,
        "run_id": run_id,
        # Seek metadata
        "tail_event_count": tail_event_count,
        "restored_from_snapshot": restored_from_snapshot,
        # Run
        "run_status": str(run_section.get("status") or "unknown"),
        "run_mode": str(run_section.get("mode") or ""),
        "run_is_running": bool(run_section.get("is_running")),
        "test_name": str(run_section.get("test_name") or ""),
        "operator": str(run_section.get("operator") or ""),
        # Mission clock
        "mission_clock_seconds": float(mission_clock["seconds"]) if isinstance(mission_clock.get("seconds"), (int, float)) else None,
        "mission_clock_state": str(mission_clock.get("state") or ""),
        # Recording
        "recording_active": bool(recording_clock.get("active")),
        "recording_elapsed_seconds": float(recording_clock["elapsed_seconds"]) if isinstance(recording_clock.get("elapsed_seconds"), (int, float)) else None,
        # Script
        "script_running": bool(script_section.get("is_running")),
        "script_name": str(script_section.get("name") or ""),
        "script_step_name": str(script_section.get("current_step_name") or ""),
        "script_is_held": bool(script_section.get("is_held")),
        # Alarms
        "active_alarm_count": int(alarms_section.get("active_alarm_count") or 0),
        "active_fault_count": int(alarms_section.get("active_fault_count") or 0),
        # Devices
        "device_count": device_count,
    }


def _update_reconstructed_playback_state(
    window: Any,
    seek_time: float,
    *,
    tail_event_count: int = 0,
    restored_from_snapshot: bool = False,
) -> None:
    """Build and store the reconstructed state on the PlaybackStateManager."""
    psm = getattr(window, "playback_state", None)
    if psm is None:
        return
    state = _build_reconstructed_playback_state(
        window,
        seek_time,
        tail_event_count=tail_event_count,
        restored_from_snapshot=restored_from_snapshot,
    )
    psm.update_reconstructed_state(state)


def _safe_get_timeline(window: Any):
    try:
        return window.timeline
    except Exception:
        return None

def _apply_exact_playback_seek_state(window: Any, seek_time: float) -> None:
    seek_time = max(0.0, float(seek_time))

    def _retime_target(target: Any) -> None:
        if target is None:
            return

        try:
            playback_clock = getattr(target, "_backend_playback_clock", None)
            if isinstance(playback_clock, dict):
                updated_clock = dict(playback_clock)
                updated_clock["position_seconds"] = seek_time
                setattr(target, "_backend_playback_clock", updated_clock)
        except Exception:
            pass

        # Prefer set_playback_time as the single coordinated update point.
        # It handles timeline, console, mission_time, aux_clock, and graph sync
        # in one call — calling those individually here would duplicate the work.
        setter = getattr(target, "set_playback_time", None)
        if callable(setter):
            setter(seek_time)
            return

        # Fallback for targets without set_playback_time (e.g. ScadaWindow).
        timeline = _safe_get_timeline(target)
        if timeline is not None:
            time_setter = getattr(timeline, "set_current_time", None)
            if callable(time_setter):
                time_setter(seek_time)

        console = getattr(target, "console", None)
        console_setter = getattr(console, "set_playback_time", None)
        if callable(console_setter):
            console_setter(seek_time)

    _retime_target(window)
    for child_name in ("controller", "scada", "script"):
        _retime_target(getattr(window, child_name, None))



def _handle_playback_advance(window: Any, previous_time: float, new_time: float) -> None:
    previous_time = max(0.0, float(previous_time))
    new_time = max(0.0, float(new_time))
    if new_time < previous_time:
        _handle_playback_seek(window, new_time)
        return

    if (new_time - previous_time) > 2.0:
        _handle_playback_seek(window, new_time)
        return

    psm = getattr(window, "playback_state", None)
    if psm is not None and psm.context is not None:
        merged_events = psm.seek_events
        event_time_keys = psm.event_time_keys
        start_dt = psm.start_dt
        last_event_index = psm.last_event_index
    else:
        merged_events = getattr(window, "playback_seek_events", getattr(window, "playback_merged_events", []))
        event_time_keys = getattr(window, "playback_event_time_keys", None)
        start_dt = getattr(window, "playback_start_dt", None)
        last_event_index = getattr(window, "playback_last_event_index", None)

    if not isinstance(start_dt, datetime):
        _handle_playback_seek(window, new_time)
        return

    previous_dt = start_dt + timedelta(seconds=previous_time)
    new_dt = start_dt + timedelta(seconds=new_time)

    if not isinstance(last_event_index, int) or last_event_index < 0:
        last_event_index = _playback_event_end_index(
            event_time_keys=event_time_keys,
            seek_dt=previous_dt,
        )

    new_event_index = _playback_event_end_index(
        event_time_keys=event_time_keys,
        seek_dt=new_dt,
    )

    if new_event_index < last_event_index:
        _handle_playback_seek(window, new_time)
        return

    for event in merged_events[last_event_index:new_event_index]:
        handler = getattr(window, "handle_structured_event", None)
        if callable(handler):
            handler(dict(event))

    if psm is not None:
        psm.update_after_advance(position=new_time, event_index=new_event_index)

    setattr(window, "playback_last_applied_time", new_time)
    setattr(window, "playback_last_event_index", new_event_index)
    _apply_exact_playback_seek_state(window, new_time)
    _update_reconstructed_playback_state(
        window,
        new_time,
        tail_event_count=new_event_index - last_event_index,
    )


def _playback_sync_path(selected_test: str) -> Path:
    digest = hashlib.sha1(str(selected_test).encode("utf-8")).hexdigest()[:16]
    return Path("/tmp") / f"mints_scada_playback_seek_{digest}.json"


def _write_playback_seek_sync(sync_path: Path | None, seek_time: float) -> None:
    if sync_path is None:
        return
    payload = {
        "seek_time_seconds": max(0.0, float(seek_time)),
        "updated_at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
    }
    tmp_path = sync_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(sync_path)


def _install_playback_seek_sync_poller(parent: QObject, *, window: Any, sync_path: Path) -> QTimer:
    timer = QTimer(parent)
    timer.setInterval(120)
    state = {"mtime_ns": None, "seek_time": None}

    def _poll() -> None:
        try:
            stat = sync_path.stat()
        except FileNotFoundError:
            return
        except Exception as exc:
            log.debug("Playback seek sync stat failed for %s: %s", sync_path, exc)
            return

        if state["mtime_ns"] == stat.st_mtime_ns:
            return
        state["mtime_ns"] = stat.st_mtime_ns

        try:
            payload = json.loads(sync_path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.debug("Playback seek sync read failed for %s: %s", sync_path, exc)
            return

        seek_time = payload.get("seek_time_seconds")
        if not isinstance(seek_time, (int, float)):
            return
        seek_time = max(0.0, float(seek_time))
        if state["seek_time"] is not None and abs(state["seek_time"] - seek_time) < 1e-9:
            return
        state["seek_time"] = seek_time
        _handle_playback_seek(window, seek_time)

    timer.timeout.connect(_poll)
    timer.start()
    _poll()
    return timer


def _load_ignitionhistory_playback(window: Any, selected_test: str) -> None:
    selected_run_ref, playback_source = _parse_playback_selection(selected_test)
    run_dir = _resolve_ignitionhistory_run_dir(selected_run_ref)

    metadata_path = run_dir / "metadata.json"
    merged_path, snapshots_dir = _playback_artifact_paths(run_dir, playback_source)

    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing playback metadata file: {metadata_path}")

    metadata = _load_json_file(metadata_path)
    merged_events = _load_jsonl_file(merged_path) if merged_path.exists() else []
    snapshot_files = sorted(snapshots_dir.glob("*.json")) if snapshots_dir.is_dir() else []

    # Build the seek index.  Events with a parseable wall-time get their
    # true timestamp; events WITHOUT a parseable timestamp are assigned the
    # timestamp of the nearest preceding timestamped event (or the run start
    # time if none precedes them).  This keeps untimestamped events in the
    # bisect-based seek path with their best-effort temporal position rather
    # than silently dropping them from playback.
    run_start_key = _datetime_to_seek_key(_parse_iso_wall_time(metadata.get("start_wall_time")))
    seek_entries: list[tuple[float, int, dict[str, Any]]] = []
    last_known_key: float | None = run_start_key
    for original_index, event in enumerate(merged_events):
        event_dt = _extract_event_wall_time(event)
        event_key = _datetime_to_seek_key(event_dt)
        if event_key is not None:
            last_known_key = event_key
        else:
            # Approximate: use nearest preceding timestamp or run start.
            event_key = last_known_key
        if event_key is None:
            continue
        seek_entries.append((event_key, original_index, event))
    seek_entries.sort(key=lambda entry: (entry[0], entry[1]))
    playback_seek_events = [event for _, _, event in seek_entries]
    playback_event_time_keys = [event_key for event_key, _, _ in seek_entries]

    setattr(window, "playback_history_dir", str(run_dir))
    setattr(window, "playback_run_id", metadata.get("run_id", run_dir.name))
    setattr(window, "playback_metadata", metadata)
    setattr(window, "playback_source", playback_source)
    setattr(window, "playback_merged_events", merged_events)
    setattr(window, "playback_seek_events", playback_seek_events)
    setattr(window, "playback_event_time_keys", playback_event_time_keys)
    setattr(window, "playback_snapshot_files", [str(path) for path in snapshot_files])

    start_dt = _parse_iso_wall_time(metadata.get("start_wall_time"))
    end_dt = _parse_iso_wall_time(metadata.get("end_wall_time"))
    event_times = [dt for dt in (_extract_event_wall_time(event) for event in merged_events) if dt is not None]

    if start_dt is None and event_times:
        start_dt = min(event_times)
    if end_dt is None and event_times:
        end_dt = max(event_times)
    if start_dt is None:
        start_dt = datetime.now().astimezone()
    if end_dt is None:
        end_dt = start_dt

    duration_s = max(0.0, (end_dt - start_dt).total_seconds())
    playback_snapshot_index = _build_playback_snapshot_index(snapshot_files=snapshot_files, start_dt=start_dt)
    setattr(window, "playback_start_dt", start_dt)
    setattr(window, "playback_end_dt", end_dt)
    setattr(window, "playback_duration_seconds", duration_s)
    setattr(window, "playback_snapshot_index", playback_snapshot_index)

    # Load initial snapshot early so it can be included in the context.
    first_snapshot = None
    if snapshot_files:
        try:
            first_snapshot = _load_playback_snapshot_payload(str(snapshot_files[0]))
        except Exception as exc:
            log.warning("Failed to load initial playback snapshot: %s", exc)

    # Populate PlaybackStateManager if one is attached to this window.
    psm = getattr(window, "playback_state", None)
    if psm is not None:
        context = PlaybackRunContext(
            run_id=metadata.get("run_id", run_dir.name),
            history_dir=str(run_dir),
            playback_source=playback_source,
            metadata=dict(metadata),
            start_dt=start_dt,
            end_dt=end_dt,
            duration_seconds=duration_s,
            snapshot_index=list(playback_snapshot_index),
            snapshot_files=[str(path) for path in snapshot_files],
            merged_events=merged_events,
            seek_events=playback_seek_events,
            event_time_keys=playback_event_time_keys,
            initial_snapshot=first_snapshot,
        )
        psm.load_context(context)

    sync_path_value = getattr(window, "playback_seek_sync_path", None)
    sync_path = Path(sync_path_value) if isinstance(sync_path_value, str) and sync_path_value else None
    sync_write = bool(getattr(window, "playback_seek_sync_write", False))

    def _bound_seek_handler(seek_time: float) -> None:
        _handle_playback_seek(window, seek_time)
        if sync_write and sync_path is not None:
            _write_playback_seek_sync(sync_path, seek_time)

    def _bound_advance_handler(previous_time: float, seek_time: float) -> None:
        _handle_playback_advance(window, previous_time, seek_time)
        if sync_write and sync_path is not None:
            _write_playback_seek_sync(sync_path, seek_time)

    setattr(window, "playback_seek_handler", _bound_seek_handler)
    setattr(window, "playback_advance_handler", _bound_advance_handler)

    # Apply initial snapshot to device catalog and child windows.
    if first_snapshot is not None:
        setattr(window, "playback_initial_snapshot", first_snapshot)
        _apply_playback_state_snapshot(window, first_snapshot)

    timeline = _safe_get_timeline(window)
    added_labels = 0
    if timeline is not None:
        timeline.min_time = 0.0
        timeline.set_total_duration(duration_s)
        for event in merged_events:
            label = _build_playback_timeline_label(event)
            if label is None:
                continue
            event_dt = _extract_event_wall_time(event)
            if event_dt is None:
                continue
            relative_s = max(0.0, (event_dt - start_dt).total_seconds())
            timeline.add_event(relative_s, label)
            added_labels += 1
        timeline.set_current_time(0.0)

    try:
        setattr(window, "playback_time", 0.0)
        setattr(window, "playback_last_applied_time", 0.0)
        setattr(window, "playback_last_event_index", 0)
    except Exception:
        pass

    playback_payload = {
        "run_id": metadata.get("run_id", run_dir.name),
        "history_dir": str(run_dir),
        "playback_source": playback_source,
        "metadata": dict(metadata),
        "merged_event_count": len(merged_events),
        "snapshot_count": len(snapshot_files),
        "snapshot_index_count": len(playback_snapshot_index),
        "timeline_label_count": added_labels,
        "duration_seconds": duration_s,
        "duration_text": f"{duration_s:.3f} s",
    }
    _dispatch_playback_loaded(window, playback_payload)

    log.info(
        "Loaded ignitionhistory playback run %s from %s with %s merged events, %s timeline labels, %s snapshots",
        metadata.get("run_id", run_dir.name),
        run_dir,
        len(merged_events),
        added_labels,
        len(snapshot_files),
    )


def _configure_logging(window_kind: str, mode: str) -> QLoggingHandler:
    formatstr = "%(asctime)s [%(name)-16.16s] [%(levelname)-5.5s] %(message)s"
    consolehandler = QLoggingHandler()
    consolehandler.setFormatter(logging.Formatter(formatstr))

    log_dir = _project_root() / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    logfile = log_dir / f"{mode}_{window_kind}.log"

    logging.basicConfig(
        level=logging.DEBUG,
        format=formatstr,
        handlers=[
            logging.FileHandler(logfile),
            logging.StreamHandler(),
            consolehandler,
        ],
        force=True,
    )
    return consolehandler


def _setup_workspace_support(
    app: QApplication,
    *,
    window: Any,
    window_role: str,
    playback_mode: bool,
    layout_profile: str,
) -> Any:
    project_root = _project_root()
    prepare_workspace_window(
        window,
        project_root=project_root,
        window_role=window_role,
        playback_mode=playback_mode,
        layout_profile=layout_profile,
    )
    controller = attach_workspace_persistence(
        window,
        project_root=project_root,
        window_role=window_role,
        playback_mode=playback_mode,
        layout_profile=layout_profile,
    )
    about_to_quit = getattr(app, "aboutToQuit", None)
    if about_to_quit is not None:
        try:
            about_to_quit.connect(controller.save_now)
        except Exception:
            pass
    return controller


def _show_window_for_workspace(window: Any, *, window_kind: str) -> None:
    restored_mode = getattr(window, "_workspace_show_mode", "normal")
    restored = bool(getattr(window, "_workspace_restored", False))

    if restored:
        if restored_mode == "fullscreen" and hasattr(window, "showFullScreen"):
            window.showFullScreen()
            return
        if restored_mode == "maximized" and hasattr(window, "showMaximized"):
            window.showMaximized()
            return
        window.show()
        return

    app = QApplication.instance()
    screens = sorted(app.screens(), key=lambda s: s.geometry().x()) if app is not None else []
    if not screens:
        window.show()
        return

    target_screen = screens[0]
    if window_kind == "scada" and len(screens) >= 2:
        target_screen = screens[1]

    if window_kind == "controller":
        geom = target_screen.geometry()
        window.setGeometry(geom)
        window.show()
        if window.windowHandle() is not None:
            window.windowHandle().setScreen(target_screen)
        window.showFullScreen()
        return

    if window_kind == "scada" and len(screens) >= 2:
        geom = target_screen.geometry()
        window.setGeometry(geom)
        window.show()
        if window.windowHandle() is not None:
            window.windowHandle().setScreen(target_screen)
        window.showFullScreen()
        return

    if window_kind == "scada":
        window.resize(1200, 800)
    window.show()


def _workspace_role(mode: str, window_kind: str) -> str:
    return f"{mode}_{window_kind}"


def _layout_profile(mode: str) -> str:
    return f"{mode}_split_window"


def _build_backend_client_identity(*, mode: str, window_kind: str, selected_test: str | None) -> dict[str, Any]:
    window_role = _workspace_role(mode, window_kind)
    return {
        "client_name": f"{window_kind}-window",
        "logical_client_id": f"gui:{mode}:{window_kind}",
        "window_role": window_role,
        "session_id": uuid4().hex,
        "mode": mode,
        "window_kind": window_kind,
        "pid": os.getpid(),
        "launcher_pid": os.getppid(),
        "selected_test": selected_test,
    }


def _build_window(window_kind: str, *, consolehandler: QLoggingHandler, playback_mode: bool, test_name: str | None) -> Any:
    if window_kind == "controller":
        return ControllerWindow(
            loghandler=consolehandler,
            autopoller=None,
            playback_mode=playback_mode,
            test_name=test_name,
            manager=None,
        )
    if window_kind == "scada":
        return ScadaWindow(
            playback_mode=playback_mode,
            test_name=test_name,
            manager=None,
        )
    raise ValueError(f"Unsupported window kind: {window_kind}")


def _abort_result_ok(reply: dict[str, Any]) -> bool:
    if not isinstance(reply, dict):
        return False
    payload = reply.get("payload", {})
    return isinstance(payload, dict) and bool(payload.get("ok"))


def _abort_failure_text(reply: dict[str, Any] | None) -> str:
    if not isinstance(reply, dict):
        return "AbortRelay returned an invalid response."

    payload = reply.get("payload", {})
    if not isinstance(payload, dict):
        return f"AbortRelay response payload is invalid: {reply!r}"

    command_response = payload.get("command_response")
    if isinstance(command_response, dict):
        command_payload = command_response.get("payload", {})
        if isinstance(command_payload, dict):
            message = command_payload.get("message") or command_payload.get("error") or command_payload.get("reason")
            if isinstance(message, str) and message.strip():
                return message.strip()

    operator_response = payload.get("operator_action_response")
    if isinstance(operator_response, dict):
        operator_payload = operator_response.get("payload", {})
        if isinstance(operator_payload, dict):
            message = operator_payload.get("message") or operator_payload.get("error")
            if isinstance(message, str) and message.strip():
                return message.strip()

    return "Backend did not accept the abort request."



def _clear_abort_result_ok(reply: dict[str, Any]) -> bool:
    if not isinstance(reply, dict):
        return False
    payload = reply.get("payload", {})
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("ok"))


def _clear_abort_failure_text(reply: dict[str, Any] | None) -> str:
    if not isinstance(reply, dict):
        return "AbortRelay returned an invalid response."

    payload = reply.get("payload", {})
    if not isinstance(payload, dict):
        return f"AbortRelay response payload is invalid: {reply!r}"

    gateway_response = payload.get("gateway_response")
    if isinstance(gateway_response, dict):
        gateway_payload = gateway_response.get("payload", {})
        if isinstance(gateway_payload, dict):
            message = gateway_payload.get("message") or gateway_payload.get("backend_error") or gateway_payload.get("error")
            if isinstance(message, str) and message.strip():
                return message.strip()

    return "Gateway did not accept the clear abort latch request."


def _make_clear_abort_latch_trigger(
    *,
    actual_window: Any,
    facade: Any,
    mode: str,
    window_kind: str,
) -> Any:
    def trigger_clear_abort_latch() -> None:
        relay_socket = str(getattr(actual_window, "abort_relay_socket_path", "") or "")
        relay_available = bool(getattr(actual_window, "abort_relay_available", False))

        if not relay_available or not relay_socket:
            QMessageBox.critical(
                actual_window,
                "Return to Normal Unavailable",
                "AbortRelay is not available for this window.",
            )
            return

        answer = QMessageBox.question(
            actual_window,
            "Back to Normal",
            "Are you sure you DO NOT want Abort and want to turn back to normal?"
            "This will clear the abort latch and reinitialize script/runtime state.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        window_role = _workspace_role(mode, window_kind)
        command_payload = {
            "command_name": "clear_abort_latch",
            "device_id": None,
            "command_args": [],
            "command_kwargs": {},
        }
        operator_action = {
            "event_kind": "operator_action",
            "action": "clear_abort_latch_requested",
            "source": "gui_clear_abort_latch_button",
            "source_window_role": window_role,
            "source_window_kind": window_kind,
            "source_mode": mode,
        }

        try:
            reply = send_clear_abort_latch_request(
                relay_socket=relay_socket,
                source_window_role=window_role,
                source_window_kind=window_kind,
                source_mode=mode,
                command_payload=command_payload,
                operator_action=operator_action,
                timeout_s=4.0,
            )
        except Exception as exc:
            log.exception("Clear abort latch request failed for %s", window_role)
            QMessageBox.critical(
                actual_window,
                "Return to Normal Failed",
                f"Clear abort latch request failed.\n\nError: {exc}",
            )
            return

        setattr(actual_window, "last_clear_abort_latch_reply", dict(reply))
        setattr(facade, "last_clear_abort_latch_reply", dict(reply))

        if _clear_abort_result_ok(reply):
            if hasattr(actual_window, "handle_script_status"):
                try:
                    actual_window.handle_script_status({"status": "idle"})
                except Exception:
                    pass
            log.warning("Clear abort latch accepted via AbortRelay for %s", window_role)
            return

        failure_text = _clear_abort_failure_text(reply)
        log.error("Clear abort latch failed via AbortRelay for %s: %s", window_role, failure_text)
        QMessageBox.critical(
            actual_window,
            "Return to Normal Failed",
            failure_text,
        )

    return trigger_clear_abort_latch


def _make_abort_trigger(
    *,
    actual_window: Any,
    facade: Any,
    mode: str,
    window_kind: str,
) -> Any:
    def trigger_abort() -> None:
        relay_socket = str(getattr(actual_window, "abort_relay_socket_path", "") or "")
        relay_available = bool(getattr(actual_window, "abort_relay_available", False))

        if not relay_available or not relay_socket:
            QMessageBox.critical(
                actual_window,
                "Abort Unavailable",
                "AbortRelay is not available for this window.",
            )
            return

        window_role = _workspace_role(mode, window_kind)

        if hasattr(actual_window, "set_status"):
            try:
                actual_window.set_status("abort")
            except Exception:
                pass
        if hasattr(actual_window, "set_script_state"):
            try:
                actual_window.set_script_state("pause")
            except Exception:
                pass

        command_payload = {
            "command_name": "abort",
            "device_id": None,
            "command_args": [],
            "command_kwargs": {},
        }
        operator_action = {
            "event_kind": "operator_action",
            "action": "abort_pressed",
            "source": "gui_abort_button",
            "source_window_role": window_role,
            "source_window_kind": window_kind,
            "source_mode": mode,
        }

        try:
            reply = send_abort_request(
                relay_socket=relay_socket,
                source_window_role=window_role,
                source_window_kind=window_kind,
                source_mode=mode,
                command_payload=command_payload,
                operator_action=operator_action,
                timeout_s=4.0,
            )
        except Exception as exc:
            log.exception("AbortRelay request failed for %s", window_role)
            QMessageBox.critical(
                actual_window,
                "Abort Failed",
                f"AbortRelay request failed.\n\nError: {exc}",
            )
            return

        setattr(actual_window, "last_abort_relay_reply", dict(reply))
        setattr(facade, "last_abort_relay_reply", dict(reply))

        if _abort_result_ok(reply):
            log.warning("Abort accepted via AbortRelay for %s", window_role)
            return

        failure_text = _abort_failure_text(reply)
        log.error("Abort failed via AbortRelay for %s: %s", window_role, failure_text)
        QMessageBox.critical(
            actual_window,
            "Abort Failed",
            failure_text,
        )

    return trigger_abort


def _wire_abort_button(*, actual_window: Any, trigger_abort: Any) -> bool:
    button = getattr(actual_window, "btn_abort", None)
    if not isinstance(button, QPushButton):
        return False

    try:
        button.clicked.disconnect()
    except Exception:
        pass

    button.clicked.connect(trigger_abort)
    setattr(actual_window, "trigger_abort_via_relay", trigger_abort)
    button.setToolTip("Send abort through AbortRelay and backend command dispatch")
    return True



def _wire_clear_abort_latch_button(*, actual_window: Any, trigger_clear_abort_latch: Any) -> bool:
    button = getattr(actual_window, "btn_clear_abort", None)
    if not isinstance(button, QPushButton):
        return False

    try:
        button.clicked.disconnect()
    except Exception:
        pass

    button.clicked.connect(trigger_clear_abort_latch)
    setattr(actual_window, "trigger_clear_abort_latch_via_relay", trigger_clear_abort_latch)
    button.setToolTip("Clear the abort latch and return to fresh initialized runtime state")
    return True


def _setup_abort_controls(*, actual_window: Any, facade: Any, mode: str, window_kind: str) -> None:
    relay_available = bool(getattr(actual_window, "abort_relay_available", False))
    relay_socket = str(getattr(actual_window, "abort_relay_socket_path", "") or "")
    if mode != "live" or not relay_available or not relay_socket:
        return

    trigger_abort = _make_abort_trigger(
        actual_window=actual_window,
        facade=facade,
        mode=mode,
        window_kind=window_kind,
    )
    trigger_clear_abort_latch = _make_clear_abort_latch_trigger(
        actual_window=actual_window,
        facade=facade,
        mode=mode,
        window_kind=window_kind,
    )

    wired_abort = _wire_abort_button(actual_window=actual_window, trigger_abort=trigger_abort)
    wired_clear = _wire_clear_abort_latch_button(
        actual_window=actual_window,
        trigger_clear_abort_latch=trigger_clear_abort_latch,
    )

    if not wired_abort:
        log.warning(
            "AbortRelay available but no standard abort button was found for %s",
            window_kind,
        )
    if not wired_clear:
        log.warning(
            "AbortRelay available but no standard clear-abort button was found for %s",
            window_kind,
        )


def _apply_abort_relay_context(*, actual_window: Any, facade: Any, abort_relay_socket: str | None) -> None:
    socket_path = abort_relay_socket or ""
    available = bool(socket_path)

    for target in (actual_window, facade):
        setattr(target, "abort_relay_socket_path", socket_path)
        setattr(target, "abort_relay_available", available)

    for child_name in ("controller", "scada", "script"):
        child = getattr(actual_window, child_name, None)
        if child is not None:
            setattr(child, "abort_relay_socket_path", socket_path)
            setattr(child, "abort_relay_available", available)


def _run_live_window(args: argparse.Namespace) -> int:
    app = QApplication(sys.argv)
    consolehandler = _configure_logging(args.window_kind, "live")
    log.info("Starting live window host for %s", args.window_kind)

    actual_window = _build_window(
        args.window_kind,
        consolehandler=consolehandler,
        playback_mode=False,
        test_name=None,
    )
    facade = WindowHostFacade(window_kind=args.window_kind, window=actual_window)
    _apply_abort_relay_context(
        actual_window=actual_window,
        facade=facade,
        abort_relay_socket=args.abort_relay_socket,
    )
    _setup_abort_controls(
        actual_window=actual_window,
        facade=facade,
        mode="live",
        window_kind=args.window_kind,
    )

    _setup_workspace_support(
        app,
        window=actual_window,
        window_role=_workspace_role("live", args.window_kind),
        playback_mode=False,
        layout_profile=_layout_profile("live"),
    )

    backend_client = BackendClient(
        socket_path=Path(args.backend_socket),
        auto_reconnect_enabled=True,
        reconnect_initial_interval_ms=750,
        reconnect_max_interval_ms=5000,
    )
    GuiBackendBridge(
        window=facade,
        backend_client=backend_client,
        mode="live",
        window_kind=args.window_kind,
        initialize_live_hardware_on_connect=(args.window_kind == "controller"),
        pending_start_run_payload=_decode_json_arg(
            args.start_run_payload_b64 or os.environ.get("MINTS_PENDING_START_RUN_B64")
        ) if args.window_kind == "controller" else None,
    )

    heartbeat_client = None
    try:
        backend_identity = _build_backend_client_identity(
            mode="live",
            window_kind=args.window_kind,
            selected_test=None,
        )
        setattr(actual_window, "backend_client_identity", dict(backend_identity))
        setattr(facade, "backend_client_identity", dict(backend_identity))
        connected_now = backend_client.connect_to_backend(
            **backend_identity,
            allow_deferred_reconnect=True,
        )
        setattr(actual_window, "backend_initial_connect_succeeded", bool(connected_now))
        setattr(facade, "backend_initial_connect_succeeded", bool(connected_now))

        heartbeat_client = SupervisorHeartbeatClient(
            socket_path=args.supervisor_socket,
            mode="live",
            window_kind=args.window_kind,
            window_role=str(backend_identity.get("window_role")),
            session_id=str(backend_identity.get("session_id")),
            parent=app,
        )
        heartbeat_client.start()
        app.aboutToQuit.connect(heartbeat_client.stop)
    except Exception as exc:
        QMessageBox.critical(
            None,
            "Backend Connection Error",
            "Failed to initialize the backend reconnect client.\n\n"
            f"Socket: {args.backend_socket}\n"
            f"Error: {exc}",
        )
        return 1

    _show_window_for_workspace(actual_window, window_kind=args.window_kind)
    exec_fn = getattr(app, "exec", app.exec_)
    try:
        return exec_fn()
    finally:
        if heartbeat_client is not None:
            heartbeat_client.stop()
        backend_client.disconnect_from_backend()


def _run_playback_window(args: argparse.Namespace) -> int:
    app = QApplication(sys.argv)
    consolehandler = _configure_logging(args.window_kind, "playback")
    selected_run_ref, playback_source = _parse_playback_selection(args.selected_test)
    log.info("Starting playback window host for %s run=%s source=%s", args.window_kind, selected_run_ref, playback_source)

    actual_window = _build_window(
        args.window_kind,
        consolehandler=consolehandler,
        playback_mode=True,
        test_name=selected_run_ref,
    )
    facade = WindowHostFacade(window_kind=args.window_kind, window=actual_window)
    actual_window.manager = facade

    psm = PlaybackStateManager()
    facade.playback_state = psm
    actual_window._playback_state_manager = psm

    sync_path = _playback_sync_path(args.selected_test)
    setattr(facade, "playback_seek_sync_path", str(sync_path))
    setattr(facade, "playback_seek_sync_write", args.window_kind == "controller")
    setattr(actual_window, "playback_seek_sync_path", str(sync_path))
    setattr(actual_window, "playback_seek_sync_write", args.window_kind == "controller")

    _apply_abort_relay_context(
        actual_window=actual_window,
        facade=facade,
        abort_relay_socket=args.abort_relay_socket,
    )

    _setup_workspace_support(
        app,
        window=actual_window,
        window_role=_workspace_role("playback", args.window_kind),
        playback_mode=True,
        layout_profile=_layout_profile("playback"),
    )

    try:
        _load_playback_device_proxies(facade)
        _load_ignitionhistory_playback(facade, args.selected_test)

        if args.window_kind == "scada":
            metadata = getattr(facade, "playback_metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            test_name = metadata.get("test_name") or metadata.get("run_id") or selected_run_ref
            source_suffix = " (Rebuild)" if playback_source == _PLAYBACK_SOURCE_REBUILD else ""
            actual_window.setWindowTitle(f"minTS SCADA - Playback - {test_name}{source_suffix}")
        else:
            _write_playback_seek_sync(sync_path, 0.0)
    except Exception as exc:
        log.error("Failed to load playback window %s: %s", args.window_kind, exc)
        QMessageBox.critical(
            None,
            "Playback Load Error",
            "Failed to load playback from ignitionhistory.\n\n"
            f"Run: {args.selected_test}\n"
            f"Window: {args.window_kind}\n"
            f"Error: {exc}",
        )
        return 1

    if args.window_kind == "scada":
        try:
            timer = _install_playback_seek_sync_poller(app, window=facade, sync_path=sync_path)
            setattr(actual_window, "_playback_seek_sync_timer", timer)
        except Exception as exc:
            log.warning("Failed to start playback seek sync poller for scada: %s", exc)

    playback_identity = _build_backend_client_identity(
        mode="playback",
        window_kind=args.window_kind,
        selected_test=args.selected_test,
    )
    heartbeat_client = SupervisorHeartbeatClient(
        socket_path=args.supervisor_socket,
        mode="playback",
        window_kind=args.window_kind,
        window_role=str(playback_identity.get("window_role")),
        session_id=str(playback_identity.get("session_id")),
        parent=app,
    )
    heartbeat_client.start()
    app.aboutToQuit.connect(heartbeat_client.stop)

    _show_window_for_workspace(actual_window, window_kind=args.window_kind)
    exec_fn = getattr(app, "exec", app.exec_)
    try:
        return exec_fn()
    finally:
        heartbeat_client.stop()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch one minTS GUI window process")
    parser.add_argument("--mode", choices=("live", "playback"), required=True)
    parser.add_argument("--window-kind", choices=("controller", "scada"), required=True)
    parser.add_argument("--backend-socket", required=True)
    parser.add_argument("--selected-test")
    parser.add_argument("--start-run-payload-b64")
    parser.add_argument("--supervisor-socket")
    parser.add_argument("--abort-relay-socket")
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.mode == "playback" and not args.selected_test:
        parser.error("--selected-test is required for playback mode")

    if args.mode == "live":
        return _run_live_window(args)
    return _run_playback_window(args)


if __name__ == "__main__":
    sys.exit(main())
