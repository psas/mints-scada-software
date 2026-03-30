from __future__ import annotations

from typing import Callable

from nexus import BusRider

from gui import AutoPoller, ExportView, GraphView
from scripts.script_runtime.script_contract import (
    DEPRECATED_MINTS_MEMBERS as CONTRACT_DEPRECATED_MINTS_MEMBERS,
    LEGACY_SCRIPT_SUPPORTED_SURFACE,
    SUPPORTED_MINTS_MEMBERS as CONTRACT_SUPPORTED_MINTS_MEMBERS,
)


class MintsScriptAPI:
    """Legacy GUI script API.

    This class intentionally keeps the historical attribute names alive while we
    migrate script execution from GUI-thread ``exec(...)`` to backend-owned
    subprocess execution.

    Commit 1 only defines the compatibility boundary; it does not remove any of
    the legacy passthrough attributes yet.

    Supported long-term script surface:
    - print(...)
    - wait(seconds)
    - abort(message=None)
    - mints.devices["device-id"]

    Legacy passthrough attributes kept temporarily during migration:
    - mints.graph
    - mints.exporter
    - mints.autopoller
    """

    SUPPORTED_SCRIPT_SURFACE = LEGACY_SCRIPT_SUPPORTED_SURFACE
    SUPPORTED_MINTS_MEMBERS = CONTRACT_SUPPORTED_MINTS_MEMBERS
    DEPRECATED_MINTS_MEMBERS = CONTRACT_DEPRECATED_MINTS_MEMBERS

    def __init__(
        self,
        devices: dict[str, BusRider] | None = None,
        graph: GraphView | None = None,
        exporter: ExportView | None = None,
        autopoller: AutoPoller | None = None,
        abort: Callable | None = None,
    ) -> None:
        self.devices = devices if devices is not None else {}
        self.graph = graph
        self.exporter = exporter
        self.autopoller = autopoller
        self.abort = abort

    @classmethod
    def describe_script_surface(cls) -> dict[str, tuple[str, ...]]:
        return {
            "supported_surface": cls.SUPPORTED_SCRIPT_SURFACE,
            "supported_mints_members": cls.SUPPORTED_MINTS_MEMBERS,
            "deprecated_mints_members": cls.DEPRECATED_MINTS_MEMBERS,
        }
