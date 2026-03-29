from __future__ import annotations

import pytest

from test_unittest_dev.helpers.inventory import load_device_ids
from test_unittest_dev.helpers.manual import manual_confirm
from test_unittest_dev.helpers.models import LabConfig


pytestmark = [pytest.mark.hardware, pytest.mark.live, pytest.mark.manual]


def test_live_device_library_not_empty_on_real_system(
    app_session,
    lab_config: LabConfig,
    artifact_recorder,
):
    artifact = {
        "test_goal": "live device library should not be empty on real hardware",
        "inventory_file": str(lab_config.inventory_file) if lab_config.inventory_file else None,
    }

    device_ids = load_device_ids(lab_config.inventory_file)
    artifact["inventory_ids"] = device_ids
    artifact["inventory_count"] = len(device_ids)

    visual_ok = manual_confirm(
        lab_config,
        "live_device_library_visual_check",
        """
        Enter live mode and inspect the controller window device library.
        Answer YES only if the visible device library is populated with real devices
        and is not blank.
        """,
        artifact,
    )
    artifact["visual_ok"] = visual_ok
    artifact_path = artifact_recorder(artifact)

    if lab_config.inventory_file is not None:
        assert device_ids, (
            f"Configured inventory file did not contain any device IDs. Evidence: {artifact_path}"
        )
    assert visual_ok, f"Visible live device library is still empty. Evidence: {artifact_path}"


def test_live_device_inventory_contains_required_ids(
    app_session,
    lab_config: LabConfig,
    artifact_recorder,
):
    if lab_config.inventory_file is None:
        pytest.fail("Pass --mints-inventory-file or set MINTS_INVENTORY_FILE.")
    if not lab_config.required_device_ids:
        pytest.fail("Pass --mints-required-device-ids or set MINTS_REQUIRED_DEVICE_IDS.")

    device_ids = load_device_ids(lab_config.inventory_file)
    missing = [device_id for device_id in lab_config.required_device_ids if device_id not in device_ids]
    artifact = {
        "test_goal": "live inventory should contain known required device IDs",
        "required_ids": lab_config.required_device_ids,
        "inventory_ids": device_ids,
        "missing_ids": missing,
    }
    artifact_path = artifact_recorder(artifact)
    assert not missing, f"Missing required device IDs: {missing}. Evidence: {artifact_path}"
