"""scripts/script_runtime/script_contract.py

Shared contract for legacy script compatibility and unified abort plumbing.

This module defines the dependency-light script contract shared by GUI,
backend, and script-runtime code. It centralizes the legacy script surface,
default script locations, canonical abort constants, and builders for the
operator-action and command-request payloads used by the unified abort path.
"""

from __future__ import annotations

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

SUPPORTED_MINTS_MEMBERS: tuple[str, ...] = ("devices",)

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
ABORT_RELAY_MESSAGE_TYPE = "abort_request"
ABORT_BEHAVIOR_LOG_ONLY = "log_only_legacy_message"
ABORT_DISPATCHED_VIA = "backend_abort_acceptance"
ABORT_ADAPTER_NAME = "abort_command"
ABORT_STATUS = "handled"
ABORT_AUTHORITY_LEVEL = "operator"
ABORT_SYSTEM_EVENT_NAME = "abort_command_accepted"
ABORT_LEGACY_LOG_MESSAGE = (
    "Abort requested. Legacy backend behavior remains log-only for now."
)


@dataclass(frozen=True)
class LegacyScriptContract:
    """Describe the legacy script surface and canonical abort contract.

    The dataclass packages the script-runtime compatibility surface into a
    stable, import-friendly object that can be exposed to GUI, backend, and
    future subprocess runtime code without pulling in heavier dependencies.

    Attributes:
        default_script_directory: Default directory searched for script files.
        default_script_filename: Default script file path used by the runtime.
        legacy_script_example_files: Example script paths preserved for legacy
            workflows and operator expectations.
        supported_globals: Global names intentionally exposed to legacy scripts.
        supported_mints_members: Supported members on the ``mints`` object.
        deprecated_mints_members: Legacy ``mints`` members preserved only as
            deprecated surface markers.
        supported_surface: Human-readable summary of the supported legacy
            scripting surface.
        abort_command_name: Canonical command name used for abort requests.
        abort_operator_action: Canonical operator-action name emitted for abort
            requests.
        abort_requested_via: Canonical source marker for relay-originated abort
            requests.
        abort_relay_message_type: Canonical relay IPC message type for abort
            requests.
        abort_behavior: Current backend behavior label for accepted abort
            requests.
        abort_dispatched_via: Canonical dispatch path label for accepted abort
            handling.
        abort_adapter_name: Canonical adapter name reported for abort handling.
        abort_status: Canonical handled status returned for accepted abort
            requests.
        abort_authority_level: Authority level associated with the abort path.
        abort_system_event_name: Canonical structured/system event name emitted
            for accepted abort requests.
        abort_legacy_log_message: Base legacy log message currently emitted for
            accepted abort requests.
    """

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
    abort_relay_message_type: str = ABORT_RELAY_MESSAGE_TYPE
    abort_behavior: str = ABORT_BEHAVIOR_LOG_ONLY
    abort_dispatched_via: str = ABORT_DISPATCHED_VIA
    abort_adapter_name: str = ABORT_ADAPTER_NAME
    abort_status: str = ABORT_STATUS
    abort_authority_level: str = ABORT_AUTHORITY_LEVEL
    abort_system_event_name: str = ABORT_SYSTEM_EVENT_NAME
    abort_legacy_log_message: str = ABORT_LEGACY_LOG_MESSAGE


LEGACY_SCRIPT_CONTRACT = LegacyScriptContract()


def describe_legacy_script_contract() -> dict[str, Any]:
    """Return a plain-JSON-friendly view of the legacy script contract.

    Returns:
        A dictionary representation of ``LEGACY_SCRIPT_CONTRACT`` with an
        embedded ``abort`` section for the canonical abort-related fields.
    """
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
            "relay_message_type": contract.abort_relay_message_type,
            "current_behavior": contract.abort_behavior,
            "dispatched_via": contract.abort_dispatched_via,
            "adapter_name": contract.abort_adapter_name,
            "status": contract.abort_status,
            "authority_level": contract.abort_authority_level,
            "system_event_name": contract.abort_system_event_name,
            "legacy_log_message": contract.abort_legacy_log_message,
        },
    }


def is_supported_mints_member(name: str) -> bool:
    """Return whether a ``mints`` attribute is part of the supported surface.

    Args:
        name: Member name to check.

    Returns:
        True when ``name`` is a supported ``mints`` member exposed to legacy
        scripts.
    """
    return name in SUPPORTED_MINTS_MEMBERS


def is_deprecated_mints_member(name: str) -> bool:
    """Return whether a ``mints`` attribute is recognized as deprecated.

    Args:
        name: Member name to check.

    Returns:
        True when ``name`` is part of the deprecated legacy ``mints`` surface.
    """
    return name in DEPRECATED_MINTS_MEMBERS


def build_abort_legacy_log_message(message: str | None = None) -> str:
    """Build the current legacy log-only abort message.

    Args:
        message: Optional caller-supplied detail message to append.

    Returns:
        The base legacy abort message, optionally extended with a ``Detail:``
        suffix when ``message`` is a non-empty string after stripping.
    """
    if isinstance(message, str):
        stripped = message.strip()
        if stripped:
            return f"{ABORT_LEGACY_LOG_MESSAGE} Detail: {stripped}"
    return ABORT_LEGACY_LOG_MESSAGE


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
    """Build the canonical operator_action payload for an abort request.

    Args:
        relay_request_id: Relay-generated request identifier for the abort.
        relay_session_id: Relay session identifier associated with the request.
        requested_at: Timestamp string for when the abort was requested.
        source_window_role: Logical source window role, when known.
        source_window_kind: Source window kind, when known.
        source_mode: Source runtime mode, such as live or playback.
        extra: Additional fields to merge into the payload.

    Returns:
        A canonical ``operator_action`` payload for the abort path. Values in
        ``extra`` override previously populated keys when provided.
    """
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
    """Build the canonical command_request payload for an abort request.

    Args:
        relay_request_id: Relay-generated request identifier for the abort.
        relay_session_id: Relay session identifier associated with the request.
        source_window_role: Logical source window role, when known.
        source_window_kind: Source window kind, when known.
        source_mode: Source runtime mode, such as live or playback.
        extra: Additional fields to merge into the payload.

    Returns:
        A canonical ``command_request`` payload for the abort path. Values in
        ``extra`` override previously populated keys when provided.
    """
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
