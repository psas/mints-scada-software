from __future__ import annotations

import pytest

from test_unittest_dev.helpers.manual import manual_confirm
from test_unittest_dev.helpers.models import LabConfig


pytestmark = [pytest.mark.gui, pytest.mark.manual]


def test_drag_and_drop_widget_into_workspace_does_not_freeze_or_crash(
    app_session,
    lab_config: LabConfig,
    artifact_recorder,
):
    artifact = {
        "test_goal": "drag/drop widget into workspace should not crash or freeze",
    }

    action_done = manual_confirm(
        lab_config,
        "drag_drop_action",
        """
        In the controller window, drag a device/widget from the library into the workspace.
        Answer YES only after the drop action has completed.
        """,
        artifact,
    )
    assert action_done, "Operator did not complete the drag/drop action."

    still_alive = manual_confirm(
        lab_config,
        "drag_drop_result",
        """
        After the drag/drop action, did the software stay responsive, avoid freezing,
        and avoid closing itself?
        """,
        artifact,
    )
    artifact["still_alive"] = still_alive
    artifact_path = artifact_recorder(artifact)
    assert still_alive, f"Drag/drop still freezes or crashes the software. Evidence: {artifact_path}"
