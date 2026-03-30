from __future__ import annotations

from backend.abort_command import (
    build_abort_dispatch_info,
    build_abort_structured_event,
    is_abort_command_payload,
    record_abort_system_event,
)
from scripts.script_runtime.script_contract import (
    ABORT_ADAPTER_NAME,
    ABORT_BEHAVIOR_LOG_ONLY,
    ABORT_COMMAND_NAME,
    ABORT_DISPATCHED_VIA,
    ABORT_STATUS,
    ABORT_SYSTEM_EVENT_NAME,
)


class FakeHealth:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def record_system_event(self, event_name: str, **kwargs) -> None:
        self.calls.append((event_name, kwargs))


def test_is_abort_command_payload_accepts_canonical_abort() -> None:
    assert is_abort_command_payload({"command_name": ABORT_COMMAND_NAME}) is True
    assert is_abort_command_payload({"command_name": "open"}) is False
    assert is_abort_command_payload({}) is False



def test_build_abort_dispatch_info_preserves_metadata_and_legacy_behavior() -> None:
    payload = {
        "command_name": "abort",
        "requested_via": "abort_relay",
        "relay_request_id": "relay-123",
        "relay_session_id": "session-456",
        "source_window_role": "controller",
        "source_window_kind": "window",
        "source_mode": "live",
        "command_kwargs": {"message": "manual e-stop requested"},
    }

    dispatch_info = build_abort_dispatch_info(payload, default_request_source="gui")

    assert dispatch_info["success"] is True
    assert dispatch_info["command_name"] == ABORT_COMMAND_NAME
    assert dispatch_info["dispatched_via"] == ABORT_DISPATCHED_VIA
    assert dispatch_info["status"] == ABORT_STATUS
    assert dispatch_info["adapter_name"] == ABORT_ADAPTER_NAME
    assert dispatch_info["behavior"] == ABORT_BEHAVIOR_LOG_ONLY
    assert dispatch_info["request_id"] == "relay-123"
    assert dispatch_info["request_source"] == "abort_relay"
    assert dispatch_info["relay_session_id"] == "session-456"
    assert dispatch_info["source_window_role"] == "controller"
    assert dispatch_info["source_window_kind"] == "window"
    assert dispatch_info["source_mode"] == "live"
    assert "manual e-stop requested" in dispatch_info["legacy_abort_message"]



def test_build_abort_structured_event_is_canonical() -> None:
    dispatch_info = build_abort_dispatch_info({"command_name": "abort"})
    event = build_abort_structured_event(dispatch_info)

    assert event["event_type"] == "system_event"
    assert event["event_name"] == ABORT_SYSTEM_EVENT_NAME
    assert event["command_name"] == ABORT_COMMAND_NAME
    assert event["behavior"] == ABORT_BEHAVIOR_LOG_ONLY



def test_record_abort_system_event_uses_canonical_name() -> None:
    fake_health = FakeHealth()
    dispatch_info = build_abort_dispatch_info(
        {
            "command_name": "abort",
            "requested_via": "abort_relay",
            "relay_request_id": "relay-abc",
        }
    )

    record_abort_system_event(fake_health, dispatch_info, current_run_id="run-001")

    assert len(fake_health.calls) == 1
    event_name, kwargs = fake_health.calls[0]
    assert event_name == ABORT_SYSTEM_EVENT_NAME
    assert kwargs["run_id"] == "run-001"
    assert kwargs["command_name"] == ABORT_COMMAND_NAME
    assert kwargs["behavior"] == ABORT_BEHAVIOR_LOG_ONLY
