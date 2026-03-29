from __future__ import annotations

from pathlib import Path

import pytest

from test_unittest_dev.helpers.capture import (
    bookmark_file,
    compare_expected_sequence,
    load_golden_trace,
    parse_packet_records,
    wait_for_new_text,
)
from test_unittest_dev.helpers.manual import manual_confirm, manual_text
from test_unittest_dev.helpers.models import LabConfig


pytestmark = [pytest.mark.hardware, pytest.mark.live, pytest.mark.manual]


def _trace_path(config: LabConfig, transition_name: str) -> Path:
    if config.main_trace_dir is None:
        pytest.fail("Pass --mints-main-trace-dir or set MINTS_MAIN_TRACE_DIR.")
    if not config.target_valve_id:
        pytest.fail("Pass --mints-target-valve-id or set MINTS_TARGET_VALVE_ID.")
    return config.main_trace_dir / f"scada_{config.target_valve_id}_{transition_name}.json"


@pytest.mark.parametrize(
    "transition_name,operator_prompt",
    [
        (
            "closed_to_open",
            """
            Put the target valve into the CLOSED starting state.
            Enter live mode if needed.
            When ready, click the target valve ONCE from the SCADA page so it transitions CLOSED -> OPEN.
            After the click, wait briefly for any outbound command packets to be written.
            Confirm only when that action is complete.
            """,
        ),
        (
            "open_to_closed",
            """
            Put the target valve into the OPEN starting state.
            Enter live mode if needed.
            When ready, click the target valve ONCE from the SCADA page so it transitions OPEN -> CLOSED.
            After the click, wait briefly for any outbound command packets to be written.
            Confirm only when that action is complete.
            """,
        ),
        (
            "repeated_toggle_sequence",
            """
            Put the target valve into the known starting state used by your main golden trace.
            Enter live mode if needed.
            When ready, perform the exact repeated toggle sequence used for the main golden trace
            from the SCADA page.
            Confirm only when the full sequence is complete.
            """,
        ),
    ],
)
def test_scada_valve_transition_matches_main_branch(
    app_session,
    lab_config: LabConfig,
    artifact_recorder,
    transition_name: str,
    operator_prompt: str,
):
    if lab_config.capture_file is None:
        pytest.fail("Pass --mints-capture-file or set MINTS_CAPTURE_FILE.")
    trace = load_golden_trace(_trace_path(lab_config, transition_name))
    start_offset = bookmark_file(lab_config.capture_file)

    artifact = {
        "test_goal": "wire-level equivalence for SCADA valve transition",
        "transition_name": transition_name,
        "target_valve_id": lab_config.target_valve_id,
        "capture_file": str(lab_config.capture_file),
        "golden_trace": trace.trace_id,
        "golden_trace_description": trace.description,
    }

    ok = manual_confirm(
        lab_config,
        f"{transition_name}_action",
        operator_prompt,
        artifact,
    )
    assert ok, "Operator reported the SCADA action was not completed."

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
    artifact["visible_toggle_confirmed"] = manual_confirm(
        lab_config,
        f"{transition_name}_visible_toggle",
        """
        Did the SCADA valve visibly switch to the expected new state and stay there,
        instead of being immediately overwritten back by a backend refresh?
        """,
        artifact,
    )

    artifact_path = artifact_recorder(artifact)
    assert matched, f"Packet comparison failed. Evidence: {artifact_path}\n{reason}"
    assert artifact["visible_toggle_confirmed"], (
        f"Valve did not visibly stay in the intended state. Evidence: {artifact_path}"
    )
