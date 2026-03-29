from __future__ import annotations

import pytest

from test_unittest_dev.helpers.capture import first_text_match
from test_unittest_dev.helpers.manual import manual_confirm
from test_unittest_dev.helpers.models import LabConfig


pytestmark = [pytest.mark.playback, pytest.mark.manual]


def test_playback_mode_does_not_mix_live_backend_logs(
    app_session,
    lab_config: LabConfig,
    artifact_recorder,
):
    artifact = {
        "test_goal": "playback log view should stay isolated from live backend logs",
        "playback_log_file": str(lab_config.playback_log_file) if lab_config.playback_log_file else None,
        "live_log_pattern": lab_config.live_log_pattern,
    }

    visually_clean = manual_confirm(
        lab_config,
        "playback_log_visual_check",
        """
        Enter PLAYBACK mode and observe the log area.
        Answer YES only if the playback log area stays replay-scoped and does NOT
        show live backend log traffic.
        """,
        artifact,
    )
    artifact["visual_ok"] = visually_clean

    if lab_config.playback_log_file and lab_config.live_log_pattern:
        found, reason = first_text_match(lab_config.playback_log_file, lab_config.live_log_pattern)
        artifact["pattern_found"] = found
        artifact["pattern_reason"] = reason
    artifact_path = artifact_recorder(artifact)

    assert visually_clean, f"Playback still visually mixed live logs. Evidence: {artifact_path}"
    if lab_config.playback_log_file and lab_config.live_log_pattern:
        assert not artifact["pattern_found"], (
            f"Playback log source still contains live-log pattern. Evidence: {artifact_path}"
        )
