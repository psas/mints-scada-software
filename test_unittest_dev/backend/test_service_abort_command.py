"""Tests for BackendService abort / clear-abort-latch command handling.

Verifies that the abort command handler latches backend abort state, stops a
running script, emits the expected IPC messages (structured_event,
script_status, command_result, state_snapshot), and that clear-abort-latch
clears state and emits a snapshot.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, Mapping
from unittest.mock import MagicMock, patch

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip


ipc_models = import_module_or_skip("backend.ipc_models")
IPCMessage = ipc_models.IPCMessage

state_store_module = import_module_or_skip("backend.state_store")
StateStore = state_store_module.StateStore

service_module = import_module_or_skip("backend.service")
BackendService = service_module.BackendService


def _collect_responses(service: BackendService, msg: IPCMessage) -> list[IPCMessage]:
    """Run handle_message and collect all yielded IPC responses."""
    return list(service.handle_message("test-client", msg))


def _abort_command_message() -> IPCMessage:
    return IPCMessage(
        type="command_request",
        payload={
            "command_name": "abort",
            "device_id": None,
            "command_args": [],
            "command_kwargs": {},
        },
    )


def _clear_abort_latch_message() -> IPCMessage:
    return IPCMessage(
        type="command_request",
        payload={
            "command_name": "clear_abort_latch",
            "device_id": None,
            "command_args": [],
            "command_kwargs": {},
        },
    )


class _MockScriptRunner:
    """Minimal mock that quacks like ScriptRunner for abort testing."""

    def __init__(self, *, running: bool = False):
        self._is_running = running
        self.stop_called = False
        self.stop_reason: str | None = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    def stop_script(self, *, reason: str = "operator_stop", timeout_s: float = 3.0) -> dict[str, Any]:
        self.stop_called = True
        self.stop_reason = reason
        self._is_running = False
        return {
            "script_id": "mock-script-1",
            "name": "test_script.py",
            "pid": 12345,
            "returncode": -15,
            "stopped_via": "abort_command",
        }


def _make_service_with_mock_script_runner(*, script_running: bool = False) -> tuple[BackendService, _MockScriptRunner]:
    """Create a BackendService with a temp directory and a mock ScriptRunner.

    This patches settings and heavy subsystems to avoid needing real hardware or
    device files.
    """
    import tempfile
    tmpdir = tempfile.mkdtemp()

    with patch.object(service_module, "settings") as mock_settings:
        mock_settings.THINGS = []
        mock_settings.DEVICE_CATALOG = []
        mock_settings.SYSTEM_ORDER = []
        mock_settings.LIVE_STARTUP_STATE = {}
        mock_settings.get_controllable_valve_ids = lambda: ()
        # Provide a minimal THINGS-like empty list
        mock_settings.THING_GROUPS = {}
        mock_settings.THING_ADDRESSES = {}

        try:
            svc = BackendService(
                project_root=tmpdir,
                socket_path=f"{tmpdir}/.backend_test.sock",
                gateway_socket_path=f"{tmpdir}/.gateway_test.sock",
            )
        except Exception:
            # If construction fails due to settings/device issues, fall back to
            # building the critical components manually.
            svc = object.__new__(BackendService)
            svc.project_root = None
            svc.started_at = "2026-01-01T00:00:00Z"
            svc.service_name = "test-backend"

            from historymanager import HistoryManager
            svc.history_manager = HistoryManager(
                project_root=tmpdir,
                enable_raw_writer=False,
                enable_rawbak_writer=False,
                enable_structured_writer=False,
            )

            from backend.health import HealthPublisher, BackendHealthMonitor
            svc.health = HealthPublisher(history_manager=svc.history_manager)

            svc.state_store = StateStore(
                service_name=svc.service_name,
                backend_started_at=svc.started_at,
            )

            svc.health_monitor = MagicMock()
            svc.health_monitor.sample_once = MagicMock()

    mock_runner = _MockScriptRunner(running=script_running)
    svc.script_runner = mock_runner
    # Ensure health_monitor.sample_once is callable
    if not hasattr(svc, "health_monitor") or svc.health_monitor is None:
        svc.health_monitor = MagicMock()

    return svc, mock_runner


class TestServiceAbortCommand(unittest.TestCase):
    """Test BackendService.handle_message for abort command_request."""

    def _make_service(self, *, script_running: bool = False):
        svc, runner = _make_service_with_mock_script_runner(script_running=script_running)
        return svc, runner

    def test_abort_latches_backend_abort_state(self):
        svc, _ = self._make_service()
        snapshot_before = svc.state_store.get_snapshot()
        self.assertFalse(snapshot_before["abort"]["abort_latched"])

        _collect_responses(svc, _abort_command_message())

        snapshot_after = svc.state_store.get_snapshot()
        self.assertTrue(snapshot_after["abort"]["abort_latched"])

    def test_abort_stops_running_script(self):
        svc, runner = self._make_service(script_running=True)
        _collect_responses(svc, _abort_command_message())

        self.assertTrue(runner.stop_called)
        self.assertEqual(runner.stop_reason, "abort")

    def test_abort_no_script_does_not_crash(self):
        svc, runner = self._make_service(script_running=False)
        responses = _collect_responses(svc, _abort_command_message())

        # Should not attempt to stop
        self.assertFalse(runner.stop_called)
        # Should still latch
        snapshot = svc.state_store.get_snapshot()
        self.assertTrue(snapshot["abort"]["abort_latched"])
        # Should still produce responses (at least structured_event + command_result + state_snapshot)
        self.assertGreaterEqual(len(responses), 2)

    def test_abort_emits_state_snapshot(self):
        svc, _ = self._make_service()
        responses = _collect_responses(svc, _abort_command_message())

        types = [r.type for r in responses]
        self.assertIn("state_snapshot", types)

        # The snapshot in the response should have abort_latched=True
        snapshot_msg = [r for r in responses if r.type == "state_snapshot"][-1]
        payload = snapshot_msg.payload
        self.assertTrue(payload.get("abort", {}).get("abort_latched"))

    def test_abort_emits_script_status_when_script_stopped(self):
        svc, _ = self._make_service(script_running=True)
        responses = _collect_responses(svc, _abort_command_message())

        types = [r.type for r in responses]
        self.assertIn("script_status", types)

        script_msg = [r for r in responses if r.type == "script_status"][0]
        self.assertEqual(script_msg.payload.get("status"), "stopped")
        self.assertEqual(script_msg.payload.get("reason"), "abort")

    def test_abort_does_not_emit_script_status_when_no_script(self):
        svc, _ = self._make_service(script_running=False)
        responses = _collect_responses(svc, _abort_command_message())

        types = [r.type for r in responses]
        self.assertNotIn("script_status", types)

    def test_abort_emits_structured_event(self):
        svc, _ = self._make_service()
        responses = _collect_responses(svc, _abort_command_message())

        types = [r.type for r in responses]
        self.assertIn("structured_event", types)

    def test_abort_emits_command_result(self):
        svc, _ = self._make_service()
        responses = _collect_responses(svc, _abort_command_message())

        types = [r.type for r in responses]
        self.assertIn("command_result", types)

        cmd_msg = [r for r in responses if r.type == "command_result"][0]
        self.assertTrue(cmd_msg.payload.get("success"))


class TestServiceClearAbortLatchCommand(unittest.TestCase):
    """Test BackendService.handle_message for clear_abort_latch command_request."""

    def _make_service(self, *, pre_latch: bool = True):
        svc, runner = _make_service_with_mock_script_runner(script_running=False)
        if pre_latch:
            svc.state_store.mark_abort_latched(
                latched_by="test",
                request_id="req-pre",
                wall_time="2026-01-01T00:01:00Z",
            )
        return svc

    def test_clear_abort_latch_clears_backend_state(self):
        svc = self._make_service(pre_latch=True)
        self.assertTrue(svc.state_store.get_snapshot()["abort"]["abort_latched"])

        _collect_responses(svc, _clear_abort_latch_message())

        self.assertFalse(svc.state_store.get_snapshot()["abort"]["abort_latched"])

    def test_clear_abort_latch_emits_state_snapshot(self):
        svc = self._make_service(pre_latch=True)
        responses = _collect_responses(svc, _clear_abort_latch_message())

        types = [r.type for r in responses]
        self.assertIn("state_snapshot", types)

        snapshot_msg = [r for r in responses if r.type == "state_snapshot"][-1]
        self.assertFalse(snapshot_msg.payload.get("abort", {}).get("abort_latched"))

    def test_clear_abort_latch_emits_command_result(self):
        svc = self._make_service(pre_latch=True)
        responses = _collect_responses(svc, _clear_abort_latch_message())

        types = [r.type for r in responses]
        self.assertIn("command_result", types)

    def test_clear_without_prior_latch_still_works(self):
        svc = self._make_service(pre_latch=False)
        responses = _collect_responses(svc, _clear_abort_latch_message())

        self.assertFalse(svc.state_store.get_snapshot()["abort"]["abort_latched"])
        types = [r.type for r in responses]
        self.assertIn("state_snapshot", types)


if __name__ == "__main__":
    unittest.main()
