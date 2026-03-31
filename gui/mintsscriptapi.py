from __future__ import annotations

from typing import Callable

from nexus import BusRider

from scripts.script_runtime.script_compat import UnsupportedLegacyScriptMember
from scripts.script_runtime.script_contract import (
    DEPRECATED_MINTS_MEMBERS as CONTRACT_DEPRECATED_MINTS_MEMBERS,
    LEGACY_SCRIPT_SUPPORTED_SURFACE,
    SUPPORTED_MINTS_MEMBERS as CONTRACT_SUPPORTED_MINTS_MEMBERS,
)


class MintsScriptAPI:
    """Minimal script API metadata for the GUI script editor.

    GUI-thread script execution is gone. The editor now launches scripts through
    subprocess-backed runtime paths only, so display-oriented legacy helpers are
    no longer exposed here.
    """

    SUPPORTED_SCRIPT_SURFACE = LEGACY_SCRIPT_SUPPORTED_SURFACE
    SUPPORTED_MINTS_MEMBERS = CONTRACT_SUPPORTED_MINTS_MEMBERS
    DEPRECATED_MINTS_MEMBERS = CONTRACT_DEPRECATED_MINTS_MEMBERS

    def __init__(
        self,
        devices: dict[str, BusRider] | None = None,
        abort: Callable | None = None,
    ) -> None:
        self.devices = devices if devices is not None else {}
        self.abort = abort

    def __getattr__(self, name: str):
        if name in self.DEPRECATED_MINTS_MEMBERS:
            raise UnsupportedLegacyScriptMember(
                f"Legacy script member {name!r} is no longer available"
            )
        raise AttributeError(name)

    @classmethod
    def describe_script_surface(cls) -> dict[str, tuple[str, ...]]:
        return {
            "supported_surface": cls.SUPPORTED_SCRIPT_SURFACE,
            "supported_mints_members": cls.SUPPORTED_MINTS_MEMBERS,
            "deprecated_mints_members": cls.DEPRECATED_MINTS_MEMBERS,
        }
