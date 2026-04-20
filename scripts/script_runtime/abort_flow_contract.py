"""scripts/script_runtime/abort_flow_contract.py

Shared payload builders for the abort-latch clear relay flow.

This module defines the canonical message types, command names, and payload
builders used when the GUI relay requests an abort-latch clear through the
operator-action path and the command-request path.
"""

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
    """Build the canonical operator_action payload for a clear-abort-latch request.

    Args:
        relay_request_id: Unique request identifier assigned by the relay flow.
        relay_session_id: Relay session identifier associated with the request.
        requested_at: Request timestamp recorded by the relay caller.
        source_window_role: Logical window role that initiated the request.
        source_window_kind: Window kind metadata for the initiating surface.
        source_mode: Mode metadata such as live or playback.
        extra: Optional additional fields to merge into the payload.

    Returns:
        A canonical operator-action payload describing the clear-abort-latch
        request and its relay/source metadata.
    """
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
    """Build the canonical command_request payload for clearing the abort latch.

    Args:
        relay_request_id: Unique request identifier assigned by the relay flow.
        relay_session_id: Relay session identifier associated with the request.
        source_window_role: Logical window role that initiated the request.
        source_window_kind: Window kind metadata for the initiating surface.
        source_mode: Mode metadata such as live or playback.
        extra: Optional additional fields to merge into the payload.

    Returns:
        A canonical command payload for the backend clear-abort-latch command,
        including empty positional and keyword command arguments plus relay and
        source metadata.
    """
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
