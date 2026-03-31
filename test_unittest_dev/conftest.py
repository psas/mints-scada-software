from __future__ import annotations

import os
from pathlib import Path

import pytest

from .helpers.artifacts import write_json_artifact
from .helpers.models import LabConfig
from .helpers.process_utils import AppSession


def _env_or_default(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("mints-live-regression")
    group.addoption("--mints-run-cmd", action="store", default=_env_or_default("MINTS_RUN_CMD"))
    group.addoption("--mints-working-dir", action="store", default=_env_or_default("MINTS_WORKING_DIR", os.getcwd()))
    group.addoption("--mints-capture-file", action="store", default=_env_or_default("MINTS_CAPTURE_FILE"))
    group.addoption("--mints-main-trace-dir", action="store", default=_env_or_default("MINTS_MAIN_TRACE_DIR"))
    group.addoption("--mints-target-valve-id", action="store", default=_env_or_default("MINTS_TARGET_VALVE_ID"))
    group.addoption("--mints-required-device-ids", action="store", default=_env_or_default("MINTS_REQUIRED_DEVICE_IDS", ""))
    group.addoption("--mints-inventory-file", action="store", default=_env_or_default("MINTS_INVENTORY_FILE"))
    group.addoption("--mints-backend-log-file", action="store", default=_env_or_default("MINTS_BACKEND_LOG_FILE"))
    group.addoption("--mints-playback-log-file", action="store", default=_env_or_default("MINTS_PLAYBACK_LOG_FILE"))
    group.addoption("--mints-live-ready-pattern", action="store", default=_env_or_default("MINTS_LIVE_READY_PATTERN"))
    group.addoption("--mints-checklist-dev-bypass-pattern", action="store", default=_env_or_default("MINTS_CHECKLIST_DEV_BYPASS_PATTERN", "dev bypass"))
    group.addoption("--mints-live-log-pattern", action="store", default=_env_or_default("MINTS_LIVE_LOG_PATTERN"))
    group.addoption("--mints-process-matchers", action="store", default=_env_or_default("MINTS_PROCESS_MATCHERS", "backend.main,gui.main,window_host.py,scada_window.py,controller_window.py"))
    group.addoption("--mints-startup-timeout", action="store", type=float, default=float(_env_or_default("MINTS_STARTUP_TIMEOUT", "30")))
    group.addoption("--mints-action-timeout", action="store", type=float, default=float(_env_or_default("MINTS_ACTION_TIMEOUT", "10")))
    group.addoption("--mints-shutdown-timeout", action="store", type=float, default=float(_env_or_default("MINTS_SHUTDOWN_TIMEOUT", "10")))
    group.addoption("--mints-artifact-dir", action="store", default=_env_or_default("MINTS_ARTIFACT_DIR", ".pytest_mints_artifacts"))
    group.addoption("--mints-no-launch", action="store_true", default=bool(_env_or_default("MINTS_NO_LAUNCH", "")))
    group.addoption("--mints-no-manual-prompts", action="store_true", default=bool(_env_or_default("MINTS_NO_MANUAL_PROMPTS", "")))


def pytest_configure(config: pytest.Config) -> None:
    for marker in [
        "hardware: requires real hardware or bench setup",
        "live: requires live mode",
        "manual: operator-assisted validation",
        "process: process lifecycle or multi-window regression",
        "backend: backend unit tests",
        "playback: playback-only regression",
        "gui: GUI interaction regression",
    ]:
        config.addinivalue_line("markers", marker)


@pytest.fixture(scope="session")
def lab_config(pytestconfig: pytest.Config) -> LabConfig:
    return LabConfig(
        run_cmd=pytestconfig.getoption("--mints-run-cmd"),
        working_dir=Path(pytestconfig.getoption("--mints-working-dir")).resolve(),
        capture_file=Path(pytestconfig.getoption("--mints-capture-file")).resolve() if pytestconfig.getoption("--mints-capture-file") else None,
        main_trace_dir=Path(pytestconfig.getoption("--mints-main-trace-dir")).resolve() if pytestconfig.getoption("--mints-main-trace-dir") else None,
        target_valve_id=pytestconfig.getoption("--mints-target-valve-id"),
        required_device_ids=_split_csv(pytestconfig.getoption("--mints-required-device-ids")),
        inventory_file=Path(pytestconfig.getoption("--mints-inventory-file")).resolve() if pytestconfig.getoption("--mints-inventory-file") else None,
        backend_log_file=Path(pytestconfig.getoption("--mints-backend-log-file")).resolve() if pytestconfig.getoption("--mints-backend-log-file") else None,
        playback_log_file=Path(pytestconfig.getoption("--mints-playback-log-file")).resolve() if pytestconfig.getoption("--mints-playback-log-file") else None,
        live_ready_pattern=pytestconfig.getoption("--mints-live-ready-pattern"),
        checklist_dev_bypass_pattern=pytestconfig.getoption("--mints-checklist-dev-bypass-pattern"),
        live_log_pattern=pytestconfig.getoption("--mints-live-log-pattern"),
        process_matchers=_split_csv(pytestconfig.getoption("--mints-process-matchers")),
        startup_timeout=float(pytestconfig.getoption("--mints-startup-timeout")),
        action_timeout=float(pytestconfig.getoption("--mints-action-timeout")),
        shutdown_timeout=float(pytestconfig.getoption("--mints-shutdown-timeout")),
        artifact_dir=Path(pytestconfig.getoption("--mints-artifact-dir")).resolve(),
        no_launch=bool(pytestconfig.getoption("--mints-no-launch")),
        no_manual_prompts=bool(pytestconfig.getoption("--mints-no-manual-prompts")),
    )


@pytest.fixture(scope="session")
def app_session(lab_config: LabConfig):
    stdout_path = lab_config.artifact_dir / "app_stdout.log"
    session = AppSession(
        cmd=None if lab_config.no_launch else lab_config.run_cmd,
        working_dir=lab_config.working_dir,
        stdout_path=stdout_path,
    )
    if not lab_config.no_launch:
        if not lab_config.run_cmd:
            pytest.fail("No launch command configured. Pass --mints-run-cmd or set MINTS_RUN_CMD.")
        session.start()
        session.wait_until_ready(
            timeout=lab_config.startup_timeout,
            pattern=lab_config.live_ready_pattern,
        )
    yield session
    if not lab_config.no_launch:
        session.stop(lab_config.shutdown_timeout)


@pytest.fixture()
def artifact_recorder(lab_config: LabConfig, request: pytest.FixtureRequest):
    def _record(payload: dict) -> Path:
        return write_json_artifact(
            base_dir=lab_config.artifact_dir,
            test_name=request.node.name,
            payload=payload,
        )
    return _record
