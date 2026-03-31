from __future__ import annotations

from typing import Any, Mapping

from scripts.script_runtime.script_contract import ABORT_REQUESTED_VIA

CLEAR_ABORT_LATCH_RELAY_MESSAGE_TYPE = "clear_abort_latch_request"
CLEAR_ABORT_LATCH_RESULT_MESSAGE_TYPE = "clear_abort_latch_result"
CLEAR_ABORT_LATCH_COMMAND_NAME = "clear_abort_latch"
CLEAR_ABORT_LATCH_OPERATOR_ACTION = "clear_abort_latch_requested"
CLEAR_ABORT_LATCH_REQUESTED_VIA = ABORT_REQUESTED_VIA
CLEAR_ABORT_LATCH_STATUS = "cleared"
CLEAR_ABORT_LATCH_SYSTEM_EVENT_NAME = "abort_latch_cleared"
CLEAR_ABORT_LATCH_LEGACY_LOG_MESSAGE = (
    "Abort latch cleared. Runtime state has been reinitialized."
)


def build_clear_abort_latch_operator_action_payload(
    *,
    relay_request_id: str,
    relay_session_id: str,
    requested_at: str,
    source_window_role: str | None = None,
    source_window_kind: str | None = None,
    source_mode: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": CLEAR_ABORT_LATCH_OPERATOR_ACTION,
        "requested_via": CLEAR_ABORT_LATCH_REQUESTED_VIA,
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


def build_clear_abort_latch_command_payload(
    *,
    relay_request_id: str,
    relay_session_id: str,
    source_window_role: str | None = None,
    source_window_kind: str | None = None,
    source_mode: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "command_name": CLEAR_ABORT_LATCH_COMMAND_NAME,
        "device_id": None,
        "command_args": [],
        "command_kwargs": {},
        "requested_via": CLEAR_ABORT_LATCH_REQUESTED_VIA,
        "relay_request_id": relay_request_id,
        "relay_session_id": relay_session_id,
        "source_window_role": source_window_role,
        "source_window_kind": source_window_kind,
        "source_mode": source_mode,
    }
    if extra:
        payload.update(dict(extra))
    return payload
