# backend/abort_command.py

from __future__ import annotations

from typing import Any, Mapping

from historymanager.manager import isoformat_z
from scripts.script_runtime.script_contract import (
    ABORT_ADAPTER_NAME,
    ABORT_AUTHORITY_LEVEL,
    ABORT_BEHAVIOR_LOG_ONLY,
    ABORT_COMMAND_NAME,
    ABORT_DISPATCHED_VIA,
    ABORT_LEGACY_LOG_MESSAGE,
    ABORT_STATUS,
    ABORT_SYSTEM_EVENT_NAME,
    build_abort_legacy_log_message,
)


def _optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _optional_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    value = payload.get(key)
    if isinstance(value, Mapping):
        return value
    return None


def is_abort_command_payload(payload: Mapping[str, Any]) -> bool:
    """Return True when a command_request payload is the canonical abort request."""
    command_name = _optional_string(payload, "command_name")
    return command_name == ABORT_COMMAND_NAME


def _extract_abort_message(payload: Mapping[str, Any]) -> str | None:
    direct_message = _optional_string(payload, "message")
    if direct_message:
        return direct_message

    command_kwargs = _optional_mapping(payload, "command_kwargs")
    if command_kwargs is None:
        return None

    for key in ("message", "msg", "reason"):
        value = _optional_string(command_kwargs, key)
        if value:
            return value
    return None


def build_abort_dispatch_info(
    payload: Mapping[str, Any],
    *,
    default_request_source: str = "gui",
) -> dict[str, Any]:
    """Build canonical dispatch_info for the unified backend abort acceptance path."""
    request_id = _optional_string(payload, "request_id") or _optional_string(
        payload,
        "relay_request_id",
    )
    request_source = _optional_string(payload, "request_source") or _optional_string(
        payload,
        "requested_via",
    )
    requested_at = _optional_string(payload, "requested_at") or isoformat_z()
    source_mode = _optional_string(payload, "source_mode") or _optional_string(
        payload,
        "run_mode",
    )
    abort_message = _extract_abort_message(payload)
    legacy_abort_message = build_abort_legacy_log_message(abort_message)

    dispatch_info = {
        "success": True,
        "command_name": ABORT_COMMAND_NAME,
        "device_id": None,
        "dispatched_via": ABORT_DISPATCHED_VIA,
        "result_summary": {
            "behavior": ABORT_BEHAVIOR_LOG_ONLY,
            "system_event": ABORT_SYSTEM_EVENT_NAME,
            "legacy_abort_message": legacy_abort_message,
            "source_window_role": _optional_string(payload, "source_window_role"),
            "source_window_kind": _optional_string(payload, "source_window_kind"),
            "source_mode": source_mode,
        },
        "error": None,
        "status": ABORT_STATUS,
        "adapter_name": ABORT_ADAPTER_NAME,
        "rejection_reason": None,
        "interlock_reason": None,
        "validation_errors": [],
        "state_reasons": [],
        "request_id": request_id,
        "request_source": request_source or default_request_source,
        "authority_level": ABORT_AUTHORITY_LEVEL,
        "run_mode": source_mode or "live",
        "requested_at": requested_at,
        "relay_request_id": _optional_string(payload, "relay_request_id"),
        "relay_session_id": _optional_string(payload, "relay_session_id"),
        "source_window_role": _optional_string(payload, "source_window_role"),
        "source_window_kind": _optional_string(payload, "source_window_kind"),
        "source_mode": source_mode,
        "abort_message": abort_message,
        "legacy_abort_message": legacy_abort_message,
        "behavior": ABORT_BEHAVIOR_LOG_ONLY,
        "system_event_name": ABORT_SYSTEM_EVENT_NAME,
    }
    return dispatch_info


def build_abort_structured_event(dispatch_info: Mapping[str, Any]) -> dict[str, Any]:
    """Build a canonical structured/system event payload for an accepted abort."""
    event = {
        "event_type": "system_event",
        "event_name": ABORT_SYSTEM_EVENT_NAME,
        "severity": "warning",
        "behavior": dispatch_info.get("behavior", ABORT_BEHAVIOR_LOG_ONLY),
        "command_name": ABORT_COMMAND_NAME,
        "request_id": dispatch_info.get("request_id"),
        "relay_request_id": dispatch_info.get("relay_request_id"),
        "relay_session_id": dispatch_info.get("relay_session_id"),
        "request_source": dispatch_info.get("request_source"),
        "authority_level": dispatch_info.get("authority_level", ABORT_AUTHORITY_LEVEL),
        "run_mode": dispatch_info.get("run_mode"),
        "requested_at": dispatch_info.get("requested_at") or isoformat_z(),
        "source_window_role": dispatch_info.get("source_window_role"),
        "source_window_kind": dispatch_info.get("source_window_kind"),
        "source_mode": dispatch_info.get("source_mode"),
        "message": dispatch_info.get("legacy_abort_message", ABORT_LEGACY_LOG_MESSAGE),
        "abort_message": dispatch_info.get("abort_message"),
    }
    return event


def record_abort_system_event(
    health: Any,
    dispatch_info: Mapping[str, Any],
    *,
    current_run_id: str | None = None,
) -> None:
    """Record the canonical backend system event for the abort acceptance path."""
    event_kwargs: dict[str, Any] = {
        "severity": "warning",
        "behavior": dispatch_info.get("behavior", ABORT_BEHAVIOR_LOG_ONLY),
        "message": dispatch_info.get("legacy_abort_message", ABORT_LEGACY_LOG_MESSAGE),
        "command_name": ABORT_COMMAND_NAME,
        "request_id": dispatch_info.get("request_id"),
        "relay_request_id": dispatch_info.get("relay_request_id"),
        "relay_session_id": dispatch_info.get("relay_session_id"),
        "request_source": dispatch_info.get("request_source"),
        "authority_level": dispatch_info.get("authority_level", ABORT_AUTHORITY_LEVEL),
        "run_mode": dispatch_info.get("run_mode"),
        "requested_at": dispatch_info.get("requested_at"),
        "source_window_role": dispatch_info.get("source_window_role"),
        "source_window_kind": dispatch_info.get("source_window_kind"),
        "source_mode": dispatch_info.get("source_mode"),
        "abort_message": dispatch_info.get("abort_message"),
    }
    if current_run_id:
        event_kwargs["run_id"] = current_run_id
    health.record_system_event(ABORT_SYSTEM_EVENT_NAME, **event_kwargs)
