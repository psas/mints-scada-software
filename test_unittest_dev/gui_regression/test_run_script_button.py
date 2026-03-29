from __future__ import annotations

import pytest

from test_unittest_dev.helpers.manual import manual_confirm
from test_unittest_dev.helpers.models import LabConfig


pytestmark = [pytest.mark.gui, pytest.mark.manual]


def test_run_script_button_does_not_crash_controller_window(
    app_session,
    lab_config: LabConfig,
    artifact_recorder,
):
    artifact = {
        "test_goal": "clicking Run Script should not crash the controller window",
    }

    action_done = manual_confirm(
        lab_config,
        "run_script_action",
        """
        Open script control in the controller window and click the Run Script button.
        Answer YES only after that click has been performed.
        """,
        artifact,
    )
    assert action_done, "Operator did not click Run Script."

    still_alive = manual_confirm(
        lab_config,
        "run_script_result",
        """
        After clicking Run Script, did the controller stay alive and avoid crashing?
        """,
        artifact,
    )
    artifact["still_alive"] = still_alive
    artifact_path = artifact_recorder(artifact)
    assert still_alive, f"Run Script still crashes the controller. Evidence: {artifact_path}"
