from __future__ import annotations

import argparse
import base64
import json
import logging
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

from PyQt5.QtCore import QObject, QTimer, Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

import settings  # noqa: E402
from gui import QLoggingHandler  # noqa: E402
from gui.backend_client import BackendClient  # noqa: E402
from gui.controller_window import ControllerWindow  # noqa: E402
from gui.device_catalog import BackendDeviceCatalog  # noqa: E402
from gui.scada_window import ScadaWindow  # noqa: E402
from gui.workspace_metadata import attach_workspace_persistence, prepare_workspace_window  # noqa: E402
from historymanager.paths import HISTORY_ROOT_DIRNAME  # noqa: E402

log = logging.getLogger(__name__)


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

    def start(self) -> None:
        if not self.socket_path:
            return
        self._send("hello")
        self._timer.start()
        log.info(
            "Started supervisor heartbeat for %s via %s",
            self.window_role,
            self.socket_path,
        )

    def stop(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
        if self.socket_path:
            self._send("goodbye")

    def send_heartbeat(self) -> None:
        if not self.socket_path:
            return
        self._send("heartbeat")

    def _send(self, message_type: str) -> None:
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

    @property
    def timeline(self):
        if self.controller is None:
            raise AttributeError("Timeline is only available for controller windows")
        return self.controller.timeline

    @property
    def playback_time(self) -> float:
        if self.controller is None:
            return 0.0
        return getattr(self.controller, "playback_time", 0.0)

    @playback_time.setter
    def playback_time(self, value: float) -> None:
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


class GuiBackendBridge:
    """Bind backend IPC messages into a single GUI window process."""

    def __init__(
        self,
        *,
        window: Any,
        backend_client: BackendClient,
        initialize_live_hardware_on_connect: bool,
        pending_start_run_payload: dict[str, Any] | None = None,
    ) -> None:
        self.window = window
        self.backend_client = backend_client
        self.initialize_live_hardware_on_connect = initialize_live_hardware_on_connect
        self.pending_start_run_payload = dict(pending_start_run_payload or {}) or None
        self._start_run_requested = False
        self.device_catalog = BackendDeviceCatalog()

        self._attach_backend_client()
        self._connect_signals()

    def _attach_backend_client(self) -> None:
        setattr(self.window, "backend_client", self.backend_client)
        setattr(self.window, "backend_device_catalog", self.device_catalog)
        setattr(self.window, "send_operator_action", self.send_operator_action)
        setattr(self.window, "request_backend_command", self.request_backend_command)
        setattr(self.window, "start_backend_script", self.start_backend_script)
        setattr(self.window, "stop_backend_script", self.stop_backend_script)

        for child_name in ("controller", "scada"):
            child = getattr(self.window, child_name, None)
            if child is not None:
                setattr(child, "backend_client", self.backend_client)
                setattr(child, "backend_device_catalog", self.device_catalog)
                setattr(child, "send_operator_action", self.send_operator_action)
                setattr(child, "request_backend_command", self.request_backend_command)
                setattr(child, "start_backend_script", self.start_backend_script)
                setattr(child, "stop_backend_script", self.stop_backend_script)

    def _connect_signals(self) -> None:
        self.backend_client.connected.connect(self.on_connected)
        self.backend_client.disconnected.connect(self.on_disconnected)
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

    def send_operator_action(self, action: str, **extra: Any) -> None:
        payload = {"action": action, **extra}
        self.backend_client.send_operator_action(payload)

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
        payload: dict[str, Any] = {
            "command_name": command_name,
            "mock_only": mock_only,
        }
        if device_id is not None:
            payload["device_id"] = device_id
        if command_args is not None:
            payload["command_args"] = list(command_args)
        if command_kwargs is not None:
            payload["command_kwargs"] = dict(command_kwargs)
        if operator_action is not None:
            payload["operator_action"] = dict(operator_action)
        self.backend_client.request_command(payload)

    def start_backend_script(
        self,
        *,
        name: str,
        command: list[str] | None = None,
        inline_python: str | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"name": name}
        if command is not None:
            payload["command"] = list(command)
        if inline_python is not None:
            payload["inline_python"] = inline_python
        if cwd is not None:
            payload["cwd"] = cwd
        if env is not None:
            payload["env"] = dict(env)
        self.backend_client.start_script(payload)

    def stop_backend_script(self, *, reason: str = "operator_stop") -> None:
        self.backend_client.stop_script(reason=reason)

    def on_connected(self) -> None:
        log.info("Connected to backend at %s", self.backend_client.socket_path)
        self.backend_client.list_devices()
        self.backend_client.request_full_state()

        if self.initialize_live_hardware_on_connect:
            try:
                self.backend_client.initialize_live_hardware()
            except Exception as exc:
                log.error("Failed to request live hardware initialization: %s", exc)

    def on_disconnected(self) -> None:
        log.warning("Disconnected from backend")
        setattr(self.window, "backend_connected", False)

    def on_hello_ack(self, payload: dict[str, Any]) -> None:
        log.info(
            "Backend hello_ack: service=%s clients=%s",
            payload.get("service_name"),
            payload.get("connected_clients"),
        )
        setattr(self.window, "backend_connected", True)
        setattr(self.window, "backend_hello_ack", dict(payload))

        if self.pending_start_run_payload is not None and not self._start_run_requested:
            try:
                self.backend_client.start_run(self.pending_start_run_payload)
                self._start_run_requested = True
                log.info("Requested backend start_run with checklist metadata: %s", self.pending_start_run_payload)
            except Exception as exc:
                log.error("Failed to request backend start_run: %s", exc)
                QMessageBox.warning(
                    None,
                    "Backend Error",
                    "Failed to request backend start_run.\n\n"
                    f"Error: {exc}",
                )

    def on_backend_status(self, payload: dict[str, Any]) -> None:
        setattr(self.window, "backend_status", dict(payload))
        handler = getattr(self.window, "handle_backend_status", None)
        if callable(handler):
            handler(dict(payload))

    def on_state_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.device_catalog.apply_state_snapshot(snapshot)
        setattr(self.window, "backend_state_snapshot", dict(snapshot))
        setattr(self.window, "backend_device_presentation", self.device_catalog.to_presentation_snapshot())

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


def _load_playback_snapshot_payload(snapshot_path: str) -> dict[str, Any]:
    return _load_json_file(Path(snapshot_path))


def _apply_playback_state_snapshot(window: Any, snapshot_payload: dict[str, Any]) -> bool:
    snapshot_state = snapshot_payload.get("state")
    if not isinstance(snapshot_state, dict):
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
) -> list[dict[str, Any]]:
    if replay_start_dt is None or seek_dt is None:
        return []

    tail_events: list[dict[str, Any]] = []
    for event in merged_events:
        event_dt = _extract_event_wall_time(event)
        if event_dt is None:
            continue
        if event_dt < replay_start_dt:
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
    snapshot_index = getattr(window, "playback_snapshot_index", [])
    merged_events = getattr(window, "playback_merged_events", [])
    start_dt = getattr(window, "playback_start_dt", None)

    seek_dt = None
    if isinstance(start_dt, datetime):
        seek_dt = start_dt + timedelta(seconds=max(0.0, seek_time))

    selected_snapshot = _find_nearest_snapshot_entry(snapshot_index, seek_time)
    replay_start_dt = start_dt
    restored_from_snapshot = False

    if selected_snapshot is not None:
        try:
            snapshot_payload = _load_playback_snapshot_payload(selected_snapshot["path"])
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
    )

    payload = {
        "seek_time_seconds": seek_time,
        "selected_snapshot": dict(selected_snapshot) if selected_snapshot is not None else None,
        "restored_from_snapshot": restored_from_snapshot,
        "tail_event_count": len(tail_events),
        "replay_start_recorded_at": replay_start_dt.isoformat() if isinstance(replay_start_dt, datetime) else None,
        "seek_recorded_at": seek_dt.isoformat() if isinstance(seek_dt, datetime) else None,
    }
    setattr(window, "playback_seek_tail_events", tail_events)
    _dispatch_playback_seek_bootstrap(window, payload)

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


def _load_ignitionhistory_playback(window: Any, selected_test: str) -> None:
    run_dir = _resolve_ignitionhistory_run_dir(selected_test)

    metadata_path = run_dir / "metadata.json"
    merged_path = run_dir / "merged.jsonl"
    snapshots_dir = run_dir / "snapshots"

    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing playback metadata file: {metadata_path}")

    metadata = _load_json_file(metadata_path)
    merged_events = _load_jsonl_file(merged_path) if merged_path.exists() else []
    snapshot_files = sorted(snapshots_dir.glob("*.json")) if snapshots_dir.is_dir() else []

    setattr(window, "playback_history_dir", str(run_dir))
    setattr(window, "playback_run_id", metadata.get("run_id", run_dir.name))
    setattr(window, "playback_metadata", metadata)
    setattr(window, "playback_merged_events", merged_events)
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
    setattr(window, "playback_seek_handler", lambda seek_time: _handle_playback_seek(window, seek_time))

    if snapshot_files:
        try:
            first_snapshot = _load_playback_snapshot_payload(str(snapshot_files[0]))
            setattr(window, "playback_initial_snapshot", first_snapshot)
            _apply_playback_state_snapshot(window, first_snapshot)
        except Exception as exc:
            log.warning("Failed to load initial playback snapshot: %s", exc)

    window.timeline.min_time = 0.0
    window.timeline.set_total_duration(duration_s)

    added_labels = 0
    for event in merged_events:
        label = _build_playback_timeline_label(event)
        if label is None:
            continue
        event_dt = _extract_event_wall_time(event)
        if event_dt is None:
            continue
        relative_s = max(0.0, (event_dt - start_dt).total_seconds())
        window.timeline.add_event(relative_s, label)
        added_labels += 1

    window.timeline.set_current_time(0.0)
    window.playback_time = 0.0

    playback_payload = {
        "run_id": metadata.get("run_id", run_dir.name),
        "history_dir": str(run_dir),
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

    _setup_workspace_support(
        app,
        window=actual_window,
        window_role=_workspace_role("live", args.window_kind),
        playback_mode=False,
        layout_profile=_layout_profile("live"),
    )

    backend_client = BackendClient(socket_path=Path(args.backend_socket))
    GuiBackendBridge(
        window=facade,
        backend_client=backend_client,
        initialize_live_hardware_on_connect=(args.window_kind == "controller"),
        pending_start_run_payload=_decode_json_arg(args.start_run_payload_b64) if args.window_kind == "controller" else None,
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
        backend_client.connect_to_backend(**backend_identity)

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
            "Failed to connect to backend service.\n\n"
            f"Socket: {args.backend_socket}\n"
            f"Error: {exc}\n\n"
            "Please start the backend first with:\n"
            "python3 main_backend.py",
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
    log.info("Starting playback window host for %s run=%s", args.window_kind, args.selected_test)

    actual_window = _build_window(
        args.window_kind,
        consolehandler=consolehandler,
        playback_mode=True,
        test_name=args.selected_test,
    )
    facade = WindowHostFacade(window_kind=args.window_kind, window=actual_window)
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
        if args.window_kind == "controller":
            _load_playback_device_proxies(facade)
            _load_ignitionhistory_playback(facade, args.selected_test)
        else:
            run_dir = _resolve_ignitionhistory_run_dir(args.selected_test)
            metadata = _load_json_file(run_dir / "metadata.json")
            test_name = metadata.get("test_name") or metadata.get("run_id") or run_dir.name
            actual_window.setWindowTitle(f"minTS SCADA - Playback - {test_name}")
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
