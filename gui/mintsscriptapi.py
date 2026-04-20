"""gui/mintsscriptapi.py

GUI-facing metadata for the legacy-compatible script surface.

This module exposes the minimal ``mints`` API description used by the GUI
script editor. It does not execute scripts in the GUI thread. Instead, it
provides the supported and deprecated surface metadata that mirrors the
subprocess-backed script runtime contract.
"""

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
    """Expose GUI-side metadata for the supported legacy script API.

    The GUI uses this class to describe the ``mints`` surface that legacy
    scripts are allowed to reference. Script execution itself is handled by the
    subprocess-backed runtime path, so this class only carries lightweight
    device and abort references plus compatibility metadata.
    """

    SUPPORTED_SCRIPT_SURFACE = LEGACY_SCRIPT_SUPPORTED_SURFACE
    SUPPORTED_MINTS_MEMBERS = CONTRACT_SUPPORTED_MINTS_MEMBERS
    DEPRECATED_MINTS_MEMBERS = CONTRACT_DEPRECATED_MINTS_MEMBERS

    def __init__(
        self,
        devices: dict[str, BusRider] | None = None,
        abort: Callable | None = None,
    ) -> None:
        """Initialize the GUI-side script API metadata container.

        Args:
            devices: Optional mapping of device IDs to GUI-visible bus-rider
                proxies used to describe the available ``mints.devices``
                surface.
            abort: Optional abort callable exposed on the legacy ``mints``
                surface.
        """
        self.devices = devices if devices is not None else {}
        self.abort = abort

    def __getattr__(self, name: str):
        """Reject unsupported legacy ``mints`` members on demand.

        Args:
            name: Missing attribute name being resolved on the instance.

        Returns:
            This method does not return successfully.

        Raises:
            UnsupportedLegacyScriptMember: The requested name is a known legacy
                member that is now explicitly unsupported.
            AttributeError: The requested name is not part of the supported or
                explicitly deprecated legacy surface.
        """
        if name in self.DEPRECATED_MINTS_MEMBERS:
            raise UnsupportedLegacyScriptMember(
                f"Legacy script member {name!r} is no longer available"
            )
        raise AttributeError(name)

    @classmethod
    def describe_script_surface(cls) -> dict[str, tuple[str, ...]]:
        """Describe the supported and deprecated legacy script surface.

        Returns:
            A dictionary containing the supported top-level script surface, the
            supported ``mints`` members, and the explicitly deprecated
            ``mints`` members.
        """
        return {
            "supported_surface": cls.SUPPORTED_SCRIPT_SURFACE,
            "supported_mints_members": cls.SUPPORTED_MINTS_MEMBERS,
            "deprecated_mints_members": cls.DEPRECATED_MINTS_MEMBERS,
        }
