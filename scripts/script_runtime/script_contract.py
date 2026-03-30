from __future__ import annotations

"""Shared contract for legacy script compatibility and unified abort plumbing.

This module is intentionally dependency-light so it can be imported from GUI,
backend, and future subprocess script-host code without dragging in PyQt or
other heavy runtime state.

Commit 1 defines the contract, the default script layout, and the canonical
abort payload builders. It does not yet switch any execution path.
"""

from dataclasses import dataclass
from typing import Any, Mapping

DEFAULT_SCRIPT_DIRECTORY = "scripts/script_sources"
DEFAULT_SCRIPT_FILENAME = f"{DEFAULT_SCRIPT_DIRECTORY}/script.py"
LEGACY_SCRIPT_EXAMPLE_FILES: tuple[str, ...] = (
    f"{DEFAULT_SCRIPT_DIRECTORY}/script.py",
    f"{DEFAULT_SCRIPT_DIRECTORY}/script_blink.py",
    f"{DEFAULT_SCRIPT_DIRECTORY}/dummy-mints.py",
)

SUPPORTED_SCRIPT_GLOBALS: tuple[str, ...] = (
    "print",
    "wait",
    "abort",
    "mints",
)

SUPPORTED_MINTS_MEMBERS: tuple[str, ...] = (
    "devices",
)

DEPRECATED_MINTS_MEMBERS: tuple[str, ...] = (
    "graph",
    "exporter",
    "autopoller",
)

LEGACY_SCRIPT_SUPPORTED_SURFACE: tuple[str, ...] = (
    "print(...)",
    "wait(seconds)",
    "abort(message=None)",
    'mints.devices["device-id"]',
)

ABORT_COMMAND_NAME = "abort"
ABORT_OPERATOR_ACTION = "abort_pressed"
ABORT_REQUESTED_VIA = "abort_relay"
ABORT_BEHAVIOR_LOG_ONLY = "log_only_legacy_message"


@dataclass(frozen=True)
class LegacyScriptContract:
    """Human-readable summary of the legacy surface we intend to preserve."""

    default_script_directory: str = DEFAULT_SCRIPT_DIRECTORY
    default_script_filename: str = DEFAULT_SCRIPT_FILENAME
    legacy_script_example_files: tuple[str, ...] = LEGACY_SCRIPT_EXAMPLE_FILES
    supported_globals: tuple[str, ...] = SUPPORTED_SCRIPT_GLOBALS
    supported_mints_members: tuple[str, ...] = SUPPORTED_MINTS_MEMBERS
    deprecated_mints_members: tuple[str, ...] = DEPRECATED_MINTS_MEMBERS
    supported_surface: tuple[str, ...] = LEGACY_SCRIPT_SUPPORTED_SURFACE
    abort_command_name: str = ABORT_COMMAND_NAME
    abort_operator_action: str = ABORT_OPERATOR_ACTION
    abort_requested_via: str = ABORT_REQUESTED_VIA
    abort_behavior: str = ABORT_BEHAVIOR_LOG_ONLY


LEGACY_SCRIPT_CONTRACT = LegacyScriptContract()


def describe_legacy_script_contract() -> dict[str, Any]:
    """Return a plain-JSON-friendly view of the contract."""

    contract = LEGACY_SCRIPT_CONTRACT
    return {
        "default_script_directory": contract.default_script_directory,
        "default_script_filename": contract.default_script_filename,
        "legacy_script_example_files": contract.legacy_script_example_files,
        "supported_globals": contract.supported_globals,
        "supported_mints_members": contract.supported_mints_members,
        "deprecated_mints_members": contract.deprecated_mints_members,
        "supported_surface": contract.supported_surface,
        "abort": {
            "command_name": contract.abort_command_name,
            "operator_action": contract.abort_operator_action,
            "requested_via": contract.abort_requested_via,
            "current_behavior": contract.abort_behavior,
        },
    }


def is_supported_mints_member(name: str) -> bool:
    return name in SUPPORTED_MINTS_MEMBERS



def is_deprecated_mints_member(name: str) -> bool:
    return name in DEPRECATED_MINTS_MEMBERS



def build_abort_operator_action_payload(
    *,
    relay_request_id: str,
    relay_session_id: str,
    requested_at: str,
    source_window_role: str | None = None,
    source_window_kind: str | None = None,
    source_mode: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical operator_action payload for an abort request."""

    payload: dict[str, Any] = {
        "action": ABORT_OPERATOR_ACTION,
        "requested_via": ABORT_REQUESTED_VIA,
        "relay_request_id": relay_request_id,
        "relay_session_id": relay_session_id,
        "source_window_role": source_window_role,
        "source_window_kind": source_window_kind,
        "source_mode": source_mode,
        "requested_at": requested_at,
    }
    if extra:
        payload.update(dict(extra))
    return payload



def build_abort_command_payload(
    *,
    relay_request_id: str,
    relay_session_id: str,
    source_window_role: str | None = None,
    source_window_kind: str | None = None,
    source_mode: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical command_request payload for an abort request."""

    payload: dict[str, Any] = {
        "command_name": ABORT_COMMAND_NAME,
        "device_id": None,
        "command_args": [],
        "command_kwargs": {},
        "requested_via": ABORT_REQUESTED_VIA,
        "relay_request_id": relay_request_id,
        "relay_session_id": relay_session_id,
        "source_window_role": source_window_role,
        "source_window_kind": source_window_kind,
        "source_mode": source_mode,
    }
    if extra:
        payload.update(dict(extra))
    return payload
