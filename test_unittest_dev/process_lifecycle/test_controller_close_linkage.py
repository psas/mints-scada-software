from __future__ import annotations

import time

import pytest

from test_unittest_dev.helpers.manual import manual_confirm
from test_unittest_dev.helpers.models import LabConfig
from test_unittest_dev.helpers.process_utils import list_matching_processes


pytestmark = [pytest.mark.process, pytest.mark.manual]


@pytest.mark.parametrize(
    "mode_name,setup_prompt",
    [
        (
            "live_non_recording",
            """
            Put the app in LIVE mode, but DO NOT start recording.
            Then close the CONTROLLER window.
            Answer YES only after that controller-close action is complete.
            """,
        ),
        (
            "playback",
            """
            Put the app in PLAYBACK mode.
            Then close the CONTROLLER window.
            Answer YES only after that controller-close action is complete.
            """,
        ),
    ],
)
def test_closing_controller_shuts_down_related_processes(
    app_session,
    lab_config: LabConfig,
    artifact_recorder,
    mode_name: str,
    setup_prompt: str,
):
    before = list_matching_processes(lab_config.process_matchers)
    artifact = {
        "test_goal": "controller close should propagate to full application shutdown path",
        "mode_name": mode_name,
        "process_matchers": lab_config.process_matchers,
        "processes_before": before,
    }

    ok = manual_confirm(lab_config, f"{mode_name}_controller_close", setup_prompt, artifact)
    assert ok, "Operator did not perform the controller-close action."

    time.sleep(lab_config.action_timeout)
    after = list_matching_processes(lab_config.process_matchers)
    artifact["processes_after"] = after
    artifact_path = artifact_recorder(artifact)

    assert not after, (
        "Related GUI/backend processes still appear to be alive after closing the controller "
        f"window in {mode_name}. Evidence: {artifact_path}"
    )
