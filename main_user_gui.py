from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from PyQt5.QtWidgets import QApplication, QMessageBox

import settings
from gui import ChecklistWindow, QLoggingHandler
from gui.backend_client import BackendClient
from gui.device_catalog import BackendDeviceCatalog
from gui.window_manager import window_manager

log = logging.getLogger(__name__)


class GuiBackendBridge:
    """Bind backend IPC messages into the existing GUI surface with minimal intrusion."""

    def __init__(
        self,
        *,
        window: Any,
        backend_client: BackendClient,
        initialize_live_hardware_on_connect: bool,
    ) -> None:
        self.window = window
        self.backend_client = backend_client
        self.initialize_live_hardware_on_connect = initialize_live_hardware_on_connect
        self.device_catalog = BackendDeviceCatalog()

        self._attach_backend_client()
        self._connect_signals()

    def _attach_backend_client(self) -> None:
        setattr(self.window, "backend_client", self.backend_client)
        setattr(self.window, "backend_device_catalog", self.device_catalog)

        for child_name in ("controller", "scada"):
            child = getattr(self.window, child_name, None)
            if child is not None:
                setattr(child, "backend_client", self.backend_client)
                setattr(child, "backend_device_catalog", self.device_catalog)

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
        self.backend_client.error_received.connect(self.on_error)

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

        handler = getattr(self.window, "handle_device_inventory", None)
        if callable(handler):
            handler(dict(payload))

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

    def on_error(self, payload: dict[str, Any]) -> None:
        code = payload.get("code", "unknown")
        message = payload.get("message", "Unknown backend error")
        log.error("Backend error [%s]: %s", code, message)

        if code in {
            "initialize_live_hardware_failed",
            "start_run_failed",
            "finish_run_failed",
        }:
            QMessageBox.warning(
                None,
                "Backend Error",
                f"{code}\n\n{message}",
            )


def _load_playback_device_proxies(window: Any) -> None:
    catalog = BackendDeviceCatalog()
    proxies = catalog.seed_from_settings_devices(settings.devices)

    setattr(window, "backend_device_catalog", catalog)
    setattr(window, "backend_device_presentation", catalog.to_presentation_snapshot())

    for proxy in proxies:
        window.addDevice(proxy, proxy.meta)


def _load_legacy_playback_metadata(window: Any, test_name: str) -> None:
    metadata_path = os.path.join("testhistory", test_name, "metadata.json")
    if not os.path.exists(metadata_path):
        log.warning("No playback metadata file found at %s", metadata_path)
        return

    try:
        with open(metadata_path, "r", encoding="utf-8") as handle:
            metadata = json.load(handle)

        if "start_time" in metadata and "end_time" in metadata:
            window.timeline.min_time = metadata["start_time"]
            window.timeline.set_total_duration(metadata["end_time"])
            log.info(
                "Playback test range: T%+.1fs to T+%.1fs",
                metadata["start_time"],
                metadata["end_time"],
            )
        elif "duration" in metadata:
            window.timeline.set_total_duration(metadata["duration"])
            log.info("Playback duration: %ss", metadata["duration"])

        for event in metadata.get("events", []):
            if isinstance(event, dict) and "time" in event and "label" in event:
                window.timeline.add_event(event["time"], event["label"])

        window.timeline.set_current_time(0.0)
        window.playback_time = 0.0

    except Exception as exc:
        log.error("Failed to load playback metadata: %s", exc)


def _configure_logging() -> QLoggingHandler:
    formatstr = "%(asctime)s [%(name)-16.16s] [%(levelname)-5.5s] %(message)s"
    consolehandler = QLoggingHandler()
    consolehandler.setFormatter(logging.Formatter(formatstr))

    if not os.path.isdir("log"):
        os.mkdir("log")

    logging.basicConfig(
        level=logging.DEBUG,
        format=formatstr,
        handlers=[
            logging.FileHandler("log/debug.log"),
            logging.StreamHandler(),
            consolehandler,
        ],
    )

    return consolehandler


def _run_playback_mode(app: QApplication, *, consolehandler: QLoggingHandler, test_name: str) -> int:
    log.info("Starting playback mode with test: %s", test_name)
    window = window_manager(
        loghandler=consolehandler,
        autopoller=None,
        playback_mode=True,
        test_name=test_name,
    )

    _load_playback_device_proxies(window)
    _load_legacy_playback_metadata(window, test_name)

    window.show()
    exec_fn = getattr(app, "exec", app.exec_)
    return exec_fn()


def _run_live_gui_mode(app: QApplication, *, consolehandler: QLoggingHandler) -> int:
    log.info("Starting live GUI client mode")

    window = window_manager(
        loghandler=consolehandler,
        autopoller=None,
        playback_mode=False,
    )

    socket_path = Path(__file__).resolve().parent / ".backend_service.sock"
    backend_client = BackendClient(socket_path=socket_path)
    GuiBackendBridge(
        window=window,
        backend_client=backend_client,
        initialize_live_hardware_on_connect=True,
    )

    try:
        backend_client.connect_to_backend(client_name="main_user_gui")
    except Exception as exc:
        QMessageBox.critical(
            None,
            "Backend Connection Error",
            "Failed to connect to backend service.\n\n"
            f"Socket: {socket_path}\n"
            f"Error: {exc}\n\n"
            "Please start the backend first with:\n"
            "python3 main_backend.py",
        )
        return 1

    window.show()
    exec_fn = getattr(app, "exec", app.exec_)

    try:
        return exec_fn()
    finally:
        backend_client.disconnect_from_backend()


def main() -> int:
    consolehandler = _configure_logging()
    log.debug("Starting user GUI entrypoint")

    app = QApplication(sys.argv)

    checklist = ChecklistWindow(settings.sender)
    if checklist.exec_() != QMessageBox.Accepted:
        log.info("User cancelled startup checklist")
        return 0

    if checklist.playback_mode:
        return _run_playback_mode(
            app,
            consolehandler=consolehandler,
            test_name=checklist.selected_test,
        )

    return _run_live_gui_mode(
        app,
        consolehandler=consolehandler,
    )


if __name__ == "__main__":
    raise SystemExit(main())