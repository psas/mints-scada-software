from __future__ import annotations

import pytest

from test_unittest_dev.helpers.manual import manual_confirm
from test_unittest_dev.helpers.models import LabConfig


pytestmark = [pytest.mark.process, pytest.mark.manual]


def test_controller_respawn_during_recording_keeps_recording_state_consistent(
    app_session,
    lab_config: LabConfig,
    artifact_recorder,
):
    artifact = {
        "test_goal": "respawned controller should keep authoritative recording state",
    }

    ok = manual_confirm(
        lab_config,
        "recording_respawn_action",
        """
        Start LIVE mode and start recording.
        Confirm that recording is active.
        Then close the CONTROLLER window and allow it to respawn.
        Answer YES only after the respawn has completed.
        """,
        artifact,
    )
    assert ok, "Operator did not complete recording-respawn flow."

    still_recording = manual_confirm(
        lab_config,
        "recording_clock_check",
        """
        After respawn, does the controller still show an ACTIVE recording state /
        recording clock instead of falling back to not-recording?
        """,
        artifact,
    )
    stop_recording_works = manual_confirm(
        lab_config,
        "stop_recording_check",
        """
        After respawn, can you still stop recording cleanly from the controller?
        """,
        artifact,
    )
    artifact["still_recording"] = still_recording
    artifact["stop_recording_works"] = stop_recording_works
    artifact_path = artifact_recorder(artifact)

    assert still_recording, f"Respawned controller lost the recording state. Evidence: {artifact_path}"
    assert stop_recording_works, f"Stop-recording path remained broken after respawn. Evidence: {artifact_path}"
