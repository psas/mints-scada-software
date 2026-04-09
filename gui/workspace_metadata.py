# gui/workspace_metadata.py

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PyQt5.QtCore import QEvent, QObject, QTimer
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtWidgets import QApplication, QWidget

log = logging.getLogger(__name__)

GUI_WORKSPACE_FILENAME = ".guiworkspace.json"
GUI_WORKSPACE_SCHEMA_VERSION = 2
_WORKSPACE_SAVE_DEBOUNCE_MS = 750


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def _encode_bytes(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _decode_bytes(value: str | None) -> bytes | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return base64.b64decode(value.encode("ascii"))
    except Exception:
        return None


@dataclass
class WindowWorkspaceState:
    window_role: str
    layout_profile: str
    playback_mode: bool
    x: int
    y: int
    width: int
    height: int
    is_maximized: bool
    is_fullscreen: bool
    screen_name: str | None = None
    screen_index: int | None = None
    qt_geometry_b64: str | None = None
    qt_state_b64: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_role": self.window_role,
            "layout_profile": self.layout_profile,
            "playback_mode": self.playback_mode,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "is_maximized": self.is_maximized,
            "is_fullscreen": self.is_fullscreen,
            "screen_name": self.screen_name,
            "screen_index": self.screen_index,
            "qt_geometry_b64": self.qt_geometry_b64,
            "qt_state_b64": self.qt_state_b64,
            "extras": dict(self.extras),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WindowWorkspaceState | None":
        try:
            extras = data.get("extras", {})
            if not isinstance(extras, dict):
                extras = {}

            screen_index = data.get("screen_index")
            if screen_index is not None:
                screen_index = int(screen_index)

            return cls(
                window_role=str(data["window_role"]),
                layout_profile=str(data.get("layout_profile") or "default"),
                playback_mode=bool(data.get("playback_mode", False)),
                x=int(data.get("x", 0)),
                y=int(data.get("y", 0)),
                width=max(1, int(data.get("width", 1200))),
                height=max(1, int(data.get("height", 800))),
                is_maximized=bool(data.get("is_maximized", False)),
                is_fullscreen=bool(data.get("is_fullscreen", False)),
                screen_name=(str(data["screen_name"]) if data.get("screen_name") else None),
                screen_index=screen_index,
                qt_geometry_b64=(str(data["qt_geometry_b64"]) if data.get("qt_geometry_b64") else None),
                qt_state_b64=(str(data["qt_state_b64"]) if data.get("qt_state_b64") else None),
                extras=extras,
                updated_at=(str(data["updated_at"]) if data.get("updated_at") else None),
            )
        except Exception:
            return None


@dataclass
class GuiWorkspaceDocument:
    schema_version: int = GUI_WORKSPACE_SCHEMA_VERSION
    updated_at: str | None = None
    windows: dict[str, WindowWorkspaceState] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "windows": {role: state.to_dict() for role, state in self.windows.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GuiWorkspaceDocument":
        windows_payload = data.get("windows", {})
        windows: dict[str, WindowWorkspaceState] = {}

        if isinstance(windows_payload, dict):
            for role, payload in windows_payload.items():
                if not isinstance(payload, dict):
                    continue
                state = WindowWorkspaceState.from_dict(payload)
                if state is not None:
                    windows[str(role)] = state

        schema_version = data.get("schema_version", GUI_WORKSPACE_SCHEMA_VERSION)
        try:
            schema_version = int(schema_version)
        except Exception:
            schema_version = GUI_WORKSPACE_SCHEMA_VERSION

        return cls(
            schema_version=schema_version,
            updated_at=(str(data["updated_at"]) if data.get("updated_at") else None),
            windows=windows,
        )


def workspace_metadata_path(project_root: str | Path) -> Path:
    return Path(project_root).expanduser().resolve() / GUI_WORKSPACE_FILENAME


def load_workspace_document(project_root: str | Path) -> GuiWorkspaceDocument:
    path = workspace_metadata_path(project_root)
    if not path.is_file():
        return GuiWorkspaceDocument()

    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("Workspace metadata root must be an object")
        document = GuiWorkspaceDocument.from_dict(payload)
        if document.schema_version > GUI_WORKSPACE_SCHEMA_VERSION:
            log.warning(
                "Workspace metadata schema version %s is newer than supported version %s; "
                "falling back to safe defaults",
                document.schema_version,
                GUI_WORKSPACE_SCHEMA_VERSION,
            )
            return GuiWorkspaceDocument()
        return document
    except Exception as exc:
        log.warning("Failed to load GUI workspace metadata from %s: %s", path, exc)
        return GuiWorkspaceDocument()


def save_workspace_document(project_root: str | Path, document: GuiWorkspaceDocument) -> None:
    path = workspace_metadata_path(project_root)
    document.schema_version = GUI_WORKSPACE_SCHEMA_VERSION
    document.updated_at = _utc_now_iso()
    _atomic_write_json(path, document.to_dict())


def _sorted_screens() -> list[Any]:
    app = QGuiApplication.instance() or QApplication.instance()
    screens = app.screens() if app is not None else []
    return sorted(screens, key=lambda screen: (screen.geometry().x(), screen.geometry().y()))


def _window_screen(window: QWidget):
    handle = window.windowHandle()
    if handle is not None and handle.screen() is not None:
        return handle.screen()
    return window.screen()


def _window_screen_name(window: QWidget) -> str | None:
    screen = _window_screen(window)
    if screen is None:
        return None
    try:
        return screen.name() or None
    except Exception:
        return None


def _window_screen_index(window: QWidget) -> int | None:
    screen = _window_screen(window)
    if screen is None:
        return None
    screens = _sorted_screens()
    for idx, candidate in enumerate(screens):
        if candidate is screen:
            return idx
        try:
            if candidate.name() == screen.name():
                return idx
        except Exception:
            continue
    return None


def _find_target_screen(*, screen_name: str | None, screen_index: int | None):
    screens = _sorted_screens()
    if not screens:
        return None

    if screen_name:
        for screen in screens:
            try:
                if screen.name() == screen_name:
                    return screen
            except Exception:
                continue

    if screen_index is not None and 0 <= screen_index < len(screens):
        return screens[screen_index]

    return None


def _move_window_to_screen(window: QWidget, target_screen: Any) -> None:
    if target_screen is None:
        return

    try:
        target_geometry = target_screen.availableGeometry()
    except Exception:
        return

    frame = window.frameGeometry()
    width = max(640, frame.width() if frame.width() > 0 else window.width())
    height = max(480, frame.height() if frame.height() > 0 else window.height())

    width = min(width, max(640, target_geometry.width()))
    height = min(height, max(480, target_geometry.height()))

    x = target_geometry.x() + max(0, (target_geometry.width() - width) // 2)
    y = target_geometry.y() + max(0, (target_geometry.height() - height) // 2)

    window.setGeometry(x, y, width, height)

    handle = window.windowHandle()
    if handle is not None:
        try:
            handle.setScreen(target_screen)
        except Exception:
            pass


def _capture_window_extras(window: QWidget) -> dict[str, Any]:
    handler = getattr(window, "capture_workspace_extras", None)
    if not callable(handler):
        return {}

    try:
        payload = handler()
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        log.debug("Failed to capture workspace extras for %s: %s", type(window).__name__, exc)
    return {}


def _apply_window_extras(window: QWidget, extras: dict[str, Any]) -> None:
    if not extras:
        return

    handler = getattr(window, "apply_workspace_extras", None)
    if not callable(handler):
        return

    try:
        handler(dict(extras))
    except Exception as exc:
        log.debug("Failed to apply workspace extras for %s: %s", type(window).__name__, exc)


def capture_window_workspace_state(
    window: QWidget,
    *,
    window_role: str,
    playback_mode: bool,
    layout_profile: str,
) -> WindowWorkspaceState:
    geometry = window.geometry()
    qt_geometry_b64 = None
    save_geometry = getattr(window, "saveGeometry", None)
    if callable(save_geometry):
        try:
            qt_geometry_b64 = _encode_bytes(bytes(save_geometry()))
        except Exception:
            qt_geometry_b64 = None

    qt_state_b64 = None
    save_state = getattr(window, "saveState", None)
    if callable(save_state):
        try:
            qt_state_b64 = _encode_bytes(bytes(save_state()))
        except Exception:
            qt_state_b64 = None

    return WindowWorkspaceState(
        window_role=window_role,
        layout_profile=layout_profile,
        playback_mode=playback_mode,
        x=geometry.x(),
        y=geometry.y(),
        width=geometry.width(),
        height=geometry.height(),
        is_maximized=window.isMaximized(),
        is_fullscreen=window.isFullScreen(),
        screen_name=_window_screen_name(window),
        screen_index=_window_screen_index(window),
        qt_geometry_b64=qt_geometry_b64,
        qt_state_b64=qt_state_b64,
        extras=_capture_window_extras(window),
        updated_at=_utc_now_iso(),
    )


def _restore_qt_geometry(window: QWidget, payload_b64: str | None) -> bool:
    restore_geometry = getattr(window, "restoreGeometry", None)
    if not callable(restore_geometry):
        return False
    raw = _decode_bytes(payload_b64)
    if raw is None:
        return False
    try:
        return bool(restore_geometry(raw))
    except Exception:
        return False


def _restore_qt_state(window: QWidget, payload_b64: str | None) -> bool:
    restore_state = getattr(window, "restoreState", None)
    if not callable(restore_state):
        return False
    raw = _decode_bytes(payload_b64)
    if raw is None:
        return False
    try:
        return bool(restore_state(raw))
    except Exception:
        return False


def _apply_fallback_geometry(window: QWidget, state: WindowWorkspaceState, target_screen: Any) -> None:
    if target_screen is not None:
        _move_window_to_screen(window, target_screen)

    target_geometry = target_screen.availableGeometry() if target_screen is not None else None

    width = max(640, state.width)
    height = max(480, state.height)
    x = state.x
    y = state.y

    if target_geometry is not None:
        width = min(width, max(640, target_geometry.width()))
        height = min(height, max(480, target_geometry.height()))
        x = min(max(x, target_geometry.left()), max(target_geometry.left(), target_geometry.right() - width + 1))
        y = min(max(y, target_geometry.top()), max(target_geometry.top(), target_geometry.bottom() - height + 1))

    window.setGeometry(x, y, width, height)


def _clamp_window_to_visible_area(window: QWidget, *, preferred_screen: Any = None) -> None:
    screens = _sorted_screens()
    if not screens:
        return

    screen = preferred_screen or _window_screen(window) or screens[0]
    try:
        available = screen.availableGeometry()
    except Exception:
        available = screens[0].availableGeometry()

    frame = window.frameGeometry()

    x = frame.x()
    y = frame.y()
    w = frame.width()
    h = frame.height()

    if w <= 0 or h <= 0:
        return

    margin = 32
    min_x = available.left() - max(0, w - margin)
    max_x = available.right() - margin
    min_y = available.top()
    max_y = available.bottom() - margin

    clamped_x = min(max(x, min_x), max_x)
    clamped_y = min(max(y, min_y), max_y)

    if clamped_x != x or clamped_y != y:
        window.move(clamped_x, clamped_y)


def prepare_workspace_window(
    window: QWidget,
    *,
    project_root: str | Path,
    window_role: str,
    playback_mode: bool,
    layout_profile: str,
) -> WindowWorkspaceState | None:
    document = load_workspace_document(project_root)
    state = document.windows.get(window_role)

    setattr(window, "_workspace_role", window_role)
    setattr(window, "_workspace_playback_mode", playback_mode)
    setattr(window, "_workspace_layout_profile", layout_profile)
    setattr(window, "_workspace_show_mode", "normal")
    setattr(window, "_workspace_restored", False)
    setattr(window, "_workspace_target_screen_name", None)
    setattr(window, "_workspace_target_screen_index", None)

    if state is None:
        return None

    target_screen = _find_target_screen(
        screen_name=state.screen_name,
        screen_index=state.screen_index,
    )

    setattr(window, "_workspace_target_screen_name", state.screen_name)
    setattr(window, "_workspace_target_screen_index", state.screen_index)

    restored_geometry = _restore_qt_geometry(window, state.qt_geometry_b64)
    if not restored_geometry:
        _apply_fallback_geometry(window, state, target_screen)
    elif target_screen is not None:
        handle = window.windowHandle()
        if handle is not None:
            try:
                handle.setScreen(target_screen)
            except Exception:
                pass

    _restore_qt_state(window, state.qt_state_b64)
    _apply_window_extras(window, state.extras)
    _clamp_window_to_visible_area(window, preferred_screen=target_screen)

    if state.is_fullscreen:
        setattr(window, "_workspace_show_mode", "fullscreen")
    elif state.is_maximized:
        setattr(window, "_workspace_show_mode", "maximized")
    else:
        setattr(window, "_workspace_show_mode", "normal")

    setattr(window, "_workspace_restored", True)
    return state


class WorkspacePersistenceController(QObject):
    def __init__(
        self,
        *,
        window: QWidget,
        project_root: str | Path,
        window_role: str,
        playback_mode: bool,
        layout_profile: str,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.project_root = Path(project_root).expanduser().resolve()
        self.window_role = window_role
        self.playback_mode = playback_mode
        self.layout_profile = layout_profile

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_WORKSPACE_SAVE_DEBOUNCE_MS)
        self._timer.timeout.connect(self.save_now)

        window.installEventFilter(self)

    def schedule_save(self) -> None:
        self._timer.start()

    def save_now(self) -> None:
        try:
            document = load_workspace_document(self.project_root)
            document.windows[self.window_role] = capture_window_workspace_state(
                self.window,
                window_role=self.window_role,
                playback_mode=self.playback_mode,
                layout_profile=self.layout_profile,
            )
            save_workspace_document(self.project_root, document)
        except Exception as exc:
            log.warning("Failed to persist GUI workspace metadata: %s", exc)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.window:
            if event.type() in {
                QEvent.Move,
                QEvent.Resize,
                QEvent.Show,
                QEvent.WindowStateChange,
                QEvent.Close,
            }:
                self.schedule_save()
        return super().eventFilter(watched, event)


def attach_workspace_persistence(
    window: QWidget,
    *,
    project_root: str | Path,
    window_role: str,
    playback_mode: bool,
    layout_profile: str,
) -> WorkspacePersistenceController:
    return WorkspacePersistenceController(
        window=window,
        project_root=project_root,
        window_role=window_role,
        playback_mode=playback_mode,
        layout_profile=layout_profile,
    )
