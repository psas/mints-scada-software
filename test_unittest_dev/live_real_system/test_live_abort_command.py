from __future__ import annotations

from pathlib import Path

import pytest

from test_unittest_dev.helpers.capture import (
    bookmark_file,
    compare_expected_sequence,
    first_text_match,
    load_golden_trace,
    parse_packet_records,
    wait_for_new_text,
)
from test_unittest_dev.helpers.manual import manual_confirm
from test_unittest_dev.helpers.models import LabConfig


pytestmark = [pytest.mark.hardware, pytest.mark.live, pytest.mark.manual]


def _abort_trace_path(config: LabConfig) -> Path:
    if config.main_trace_dir is None:
        pytest.fail("Pass --mints-main-trace-dir or set MINTS_MAIN_TRACE_DIR.")
    return config.main_trace_dir / "abort_accepted.json"


def test_abort_request_matches_main_accepted_path(
    app_session,
    lab_config: LabConfig,
    artifact_recorder,
):
    if lab_config.capture_file is None:
        pytest.fail("Pass --mints-capture-file or set MINTS_CAPTURE_FILE.")
    trace = load_golden_trace(_abort_trace_path(lab_config))
    start_offset = bookmark_file(lab_config.capture_file)

    artifact = {
        "test_goal": "abort request should follow the same accepted path as main",
        "capture_file": str(lab_config.capture_file),
        "golden_trace": trace.trace_id,
        "golden_trace_description": trace.description,
    }

    ok = manual_confirm(
        lab_config,
        "abort_valid_state",
        """
        Put the system into the exact live state where MAIN accepts Abort.
        Then press Abort from the GUI path you intend to support.
        Confirm only after the Abort action has been issued.
        """,
        artifact,
    )
    assert ok, "Operator did not complete the Abort action."

    new_text = wait_for_new_text(
        lab_config.capture_file,
        start_offset,
        lab_config.action_timeout,
    )
    actual_packets = parse_packet_records(new_text)
    matched, reason = compare_expected_sequence(trace.expected_packets, actual_packets)
    artifact["captured_text"] = new_text
    artifact["captured_packet_count"] = len(actual_packets)
    artifact["comparison_reason"] = reason
    artifact["matched"] = matched
    artifact["rejection_popup_shown"] = not manual_confirm(
        lab_config,
        "abort_popup_check",
        """
        Did the GUI avoid showing the popup:
        "Backend did not accept the abort request." ?
        Answer YES only if that rejection popup did NOT appear.
        """,
        artifact,
    )

    artifact_path = artifact_recorder(artifact)
    assert matched, f"Abort packet comparison failed. Evidence: {artifact_path}\n{reason}"
    assert not artifact["rejection_popup_shown"], (
        f"Abort rejection popup still appeared. Evidence: {artifact_path}"
    )


def test_abort_is_disabled_or_cleanly_rejected_when_invalid(
    app_session,
    lab_config: LabConfig,
    artifact_recorder,
):
    artifact = {
        "test_goal": "abort should be unavailable or explicitly rejected in invalid state",
    }

    ok = manual_confirm(
        lab_config,
        "abort_invalid_state_setup",
        """
        Put the system into a state where Abort SHOULD NOT be accepted.
        Try the Abort path if the UI still offers it.
        Answer YES only if the invalid-state check has been performed.
        """,
        artifact,
    )
    assert ok, "Operator did not perform the invalid-state Abort check."

    behaved_correctly = manual_confirm(
        lab_config,
        "abort_invalid_state_result",
        """
        In the invalid state, was Abort either unavailable, disabled,
        or rejected in a way that matches your intended design?
        """,
        artifact,
    )
    artifact["behaved_correctly"] = behaved_correctly
    artifact_path = artifact_recorder(artifact)
    assert behaved_correctly, f"Abort invalid-state behavior is still wrong. Evidence: {artifact_path}"
