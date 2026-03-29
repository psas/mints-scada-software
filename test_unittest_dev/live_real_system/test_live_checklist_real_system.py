from __future__ import annotations

import pytest

from test_unittest_dev.helpers.capture import first_text_match
from test_unittest_dev.helpers.manual import manual_confirm, manual_text
from test_unittest_dev.helpers.models import LabConfig


pytestmark = [pytest.mark.hardware, pytest.mark.live, pytest.mark.manual]


def test_checklist_does_not_show_dev_bypass_on_real_system(
    app_session,
    lab_config: LabConfig,
    artifact_recorder,
):
    artifact = {
        "test_goal": "checklist should not show dev bypass when connected to real system",
        "pattern": lab_config.checklist_dev_bypass_pattern,
    }

    visually_clean = manual_confirm(
        lab_config,
        "checklist_open_and_check",
        f"""
        Open the checklist window while plugged into the real system.
        Answer YES only if the checklist does NOT show the text/pattern
        {lab_config.checklist_dev_bypass_pattern!r} and the displayed devices look correct.
        """,
        artifact,
    )
    artifact["visual_ok"] = visually_clean
    artifact["operator_note"] = manual_text(
        lab_config,
        "checklist_operator_note",
        "Optional: type a short note about which devices or rows looked wrong. Press Enter for blank.",
        artifact,
    )
    artifact_path = artifact_recorder(artifact)
    assert visually_clean, f"Checklist still looked like dev bypass / wrong content. Evidence: {artifact_path}"
