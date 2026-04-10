# backend/clear_abort_latch_command.py

"""Canonical clear-abort-latch helpers for backend dispatch and event recording.

This module normalizes accepted clear-abort-latch request payloads into the
backend's canonical dispatch shape, builds the matching structured system
event, and records the same event through the health publisher path.
"""

from __future__ import annotations

from typing import Any, Mapping

from historymanager.manager import isoformat_z
from scripts.script_runtime.abort_flow_contract import (
    CLEAR_ABORT_LATCH_COMMAND_NAME,
    CLEAR_ABORT_LATCH_LEGACY_LOG_MESSAGE,
    CLEAR_ABORT_LATCH_STATUS,
    CLEAR_ABORT_LATCH_SYSTEM_EVENT_NAME,
)


def _optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    """Return a stripped string value from a mapping entry.

    Args:
        payload: Mapping to read from.
        key: Mapping key to inspect.

    Returns:
        The stripped string value, or None when the key is missing, not a
        string, or only contains whitespace.
    """
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def is_clear_abort_latch_command_payload(payload: Mapping[str, Any]) -> bool:
    """Return whether a command request payload targets clear-abort-latch.

    Args:
        payload: Command request payload to inspect.

    Returns:
        True when ``command_name`` matches the canonical clear-abort-latch
        command name.
    """
    command_name = _optional_string(payload, "command_name")
    return command_name == CLEAR_ABORT_LATCH_COMMAND_NAME


def build_clear_abort_latch_dispatch_info(
    payload: Mapping[str, Any],
    *,
    default_request_source: str = "gui",
) -> dict[str, Any]:
    """Build the canonical dispatch metadata for an accepted clear-abort-latch request.

    This normalizes request identity, request-source metadata, and mode
    metadata into the backend's canonical clear-abort-latch
    ``dispatch_info`` shape used by downstream logging and system-event
    publication.

    Args:
        payload: Clear-abort-latch request payload received by the backend
            acceptance path.
        default_request_source: Fallback request source when the payload does
            not declare one.

    Returns:
        A canonical clear-abort-latch ``dispatch_info`` dictionary populated
        with accepted status, request metadata, source window metadata, and
        the legacy clear message used by system-event paths.
    """
    request_id = _optional_string(payload, "request_id") or _optional_string(
        payload, "relay_request_id"
    )
    request_source = _optional_string(payload, "request_source") or _optional_string(
        payload, "requested_via"
    )
    requested_at = _optional_string(payload, "requested_at") or isoformat_z()
    source_mode = _optional_string(payload, "source_mode") or _optional_string(
        payload, "run_mode"
    )
    return {
        "success": True,
        "command_name": CLEAR_ABORT_LATCH_COMMAND_NAME,
        "device_id": None,
        "error": None,
        "status": CLEAR_ABORT_LATCH_STATUS,
        "request_id": request_id,
        "request_source": request_source or default_request_source,
        "run_mode": source_mode or "live",
        "requested_at": requested_at,
        "relay_request_id": _optional_string(payload, "relay_request_id"),
        "relay_session_id": _optional_string(payload, "relay_session_id"),
        "source_window_role": _optional_string(payload, "source_window_role"),
        "source_window_kind": _optional_string(payload, "source_window_kind"),
        "source_mode": source_mode,
        "legacy_clear_message": CLEAR_ABORT_LATCH_LEGACY_LOG_MESSAGE,
        "system_event_name": CLEAR_ABORT_LATCH_SYSTEM_EVENT_NAME,
    }


def build_clear_abort_latch_structured_event(
    dispatch_info: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the canonical structured system event for clear-abort-latch.

    Args:
        dispatch_info: Canonical clear-abort-latch dispatch metadata produced
            by ``build_clear_abort_latch_dispatch_info``.

    Returns:
        A structured ``system_event`` payload that mirrors the accepted
        clear-abort-latch metadata and preserves the legacy clear message used
        elsewhere in the backend.
    """
    return {
        "event_type": "system_event",
        "event_name": CLEAR_ABORT_LATCH_SYSTEM_EVENT_NAME,
        "severity": "warning",
        "command_name": CLEAR_ABORT_LATCH_COMMAND_NAME,
        "request_id": dispatch_info.get("request_id"),
        "relay_request_id": dispatch_info.get("relay_request_id"),
        "relay_session_id": dispatch_info.get("relay_session_id"),
        "request_source": dispatch_info.get("request_source"),
        "run_mode": dispatch_info.get("run_mode"),
        "requested_at": dispatch_info.get("requested_at") or isoformat_z(),
        "source_window_role": dispatch_info.get("source_window_role"),
        "source_window_kind": dispatch_info.get("source_window_kind"),
        "source_mode": dispatch_info.get("source_mode"),
        "message": dispatch_info.get(
            "legacy_clear_message",
            CLEAR_ABORT_LATCH_LEGACY_LOG_MESSAGE,
        ),
    }


def record_clear_abort_latch_system_event(
    health: Any,
    dispatch_info: Mapping[str, Any],
    *,
    current_run_id: str | None = None,
) -> None:
    """Record the canonical clear-abort-latch system event through health.

    Args:
        health: Health publisher object that exposes ``record_system_event``.
        dispatch_info: Canonical clear-abort-latch dispatch metadata produced
            by ``build_clear_abort_latch_dispatch_info``.
        current_run_id: Active run identifier to attach to the system event
            when one exists.

    Returns:
        None.
    """
    event_kwargs: dict[str, Any] = {
        "severity": "warning",
        "message": dispatch_info.get(
            "legacy_clear_message",
            CLEAR_ABORT_LATCH_LEGACY_LOG_MESSAGE,
        ),
        "command_name": CLEAR_ABORT_LATCH_COMMAND_NAME,
        "request_id": dispatch_info.get("request_id"),
        "relay_request_id": dispatch_info.get("relay_request_id"),
        "relay_session_id": dispatch_info.get("relay_session_id"),
        "request_source": dispatch_info.get("request_source"),
        "run_mode": dispatch_info.get("run_mode"),
        "requested_at": dispatch_info.get("requested_at"),
        "source_window_role": dispatch_info.get("source_window_role"),
        "source_window_kind": dispatch_info.get("source_window_kind"),
        "source_mode": dispatch_info.get("source_mode"),
    }
    if current_run_id:
        event_kwargs["run_id"] = current_run_id
    health.record_system_event(CLEAR_ABORT_LATCH_SYSTEM_EVENT_NAME, **event_kwargs)
