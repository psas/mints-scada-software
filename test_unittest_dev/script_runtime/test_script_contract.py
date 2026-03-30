from pathlib import Path

from scripts.script_runtime.script_contract import (
    ABORT_BEHAVIOR_LOG_ONLY,
    ABORT_COMMAND_NAME,
    ABORT_OPERATOR_ACTION,
    ABORT_REQUESTED_VIA,
    DEFAULT_SCRIPT_DIRECTORY,
    DEFAULT_SCRIPT_FILENAME,
    DEPRECATED_MINTS_MEMBERS,
    LEGACY_SCRIPT_CONTRACT,
    LEGACY_SCRIPT_EXAMPLE_FILES,
    LEGACY_SCRIPT_SUPPORTED_SURFACE,
    SUPPORTED_MINTS_MEMBERS,
    build_abort_command_payload,
    build_abort_operator_action_payload,
    describe_legacy_script_contract,
)


def test_contract_lists_supported_and_deprecated_surfaces():
    assert LEGACY_SCRIPT_CONTRACT.supported_surface == LEGACY_SCRIPT_SUPPORTED_SURFACE
    assert SUPPORTED_MINTS_MEMBERS == ("devices",)
    assert DEPRECATED_MINTS_MEMBERS == ("graph", "exporter", "autopoller")


def test_contract_lists_default_script_layout():
    assert DEFAULT_SCRIPT_DIRECTORY == "scripts/script_sources"
    assert DEFAULT_SCRIPT_FILENAME == "scripts/script_sources/script.py"
    assert LEGACY_SCRIPT_EXAMPLE_FILES == (
        "scripts/script_sources/script.py",
        "scripts/script_sources/script_blink.py",
        "scripts/script_sources/dummy-mints.py",
    )



def test_abort_command_payload_uses_canonical_defaults():
    payload = build_abort_command_payload(
        relay_request_id="req-1",
        relay_session_id="sess-1",
        source_window_role="controller",
        source_window_kind="controller",
        source_mode="live",
    )

    assert payload["command_name"] == ABORT_COMMAND_NAME
    assert payload["requested_via"] == ABORT_REQUESTED_VIA
    assert payload["relay_request_id"] == "req-1"
    assert payload["relay_session_id"] == "sess-1"
    assert payload["device_id"] is None
    assert payload["command_args"] == []
    assert payload["command_kwargs"] == {}



def test_abort_operator_action_payload_uses_canonical_defaults():
    payload = build_abort_operator_action_payload(
        relay_request_id="req-2",
        relay_session_id="sess-2",
        requested_at="2026-03-30T00:00:00.000Z",
        source_window_role="scada",
        source_window_kind="scada",
        source_mode="live",
    )

    assert payload["action"] == ABORT_OPERATOR_ACTION
    assert payload["requested_via"] == ABORT_REQUESTED_VIA
    assert payload["relay_request_id"] == "req-2"
    assert payload["relay_session_id"] == "sess-2"
    assert payload["requested_at"] == "2026-03-30T00:00:00.000Z"



def test_contract_description_is_json_friendly():
    description = describe_legacy_script_contract()

    assert description["default_script_directory"] == DEFAULT_SCRIPT_DIRECTORY
    assert description["default_script_filename"] == DEFAULT_SCRIPT_FILENAME
    assert description["legacy_script_example_files"] == LEGACY_SCRIPT_EXAMPLE_FILES
    assert description["supported_globals"] == LEGACY_SCRIPT_CONTRACT.supported_globals
    assert description["supported_mints_members"] == LEGACY_SCRIPT_CONTRACT.supported_mints_members
    assert description["deprecated_mints_members"] == LEGACY_SCRIPT_CONTRACT.deprecated_mints_members
    assert description["abort"]["current_behavior"] == ABORT_BEHAVIOR_LOG_ONLY



def test_example_script_files_exist_in_scripts_directory():
    for relative_path in LEGACY_SCRIPT_EXAMPLE_FILES:
        assert str(Path(relative_path).parent) == DEFAULT_SCRIPT_DIRECTORY
