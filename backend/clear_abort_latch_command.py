# backend/clear_abort_latch_command.py

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
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def is_clear_abort_latch_command_payload(payload: Mapping[str, Any]) -> bool:
    command_name = _optional_string(payload, "command_name")
    return command_name == CLEAR_ABORT_LATCH_COMMAND_NAME


def build_clear_abort_latch_dispatch_info(
    payload: Mapping[str, Any],
    *,
    default_request_source: str = "gui",
) -> dict[str, Any]:
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


def build_clear_abort_latch_structured_event(dispatch_info: Mapping[str, Any]) -> dict[str, Any]:
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
        "message": dispatch_info.get("legacy_clear_message", CLEAR_ABORT_LATCH_LEGACY_LOG_MESSAGE),
    }


def record_clear_abort_latch_system_event(
    health: Any,
    dispatch_info: Mapping[str, Any],
    *,
    current_run_id: str | None = None,
) -> None:
    event_kwargs: dict[str, Any] = {
        "severity": "warning",
        "message": dispatch_info.get("legacy_clear_message", CLEAR_ABORT_LATCH_LEGACY_LOG_MESSAGE),
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
