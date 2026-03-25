from __future__ import annotations

import time
import unittest

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip, wait_until


script_runner_module = import_module_or_skip("backend.script_runner")
ScriptRunner = script_runner_module.ScriptRunner


class TestScriptRunnerPlanMode(unittest.TestCase):
    def test_start_plan_script_reports_hold_capability(self):
        progress_events = []
        runner = ScriptRunner(progress_callback=lambda payload: progress_events.append(dict(payload)))

        result = runner.start_script(
            {
                "name": "demo-plan",
                "plan_steps": [
                    {"type": "note", "message": "hello"},
                    {"type": "sleep", "seconds": 0.05},
                ],
            },
            script_id="script-1",
            on_exit=lambda payload: None,
        )
        self.addCleanup(lambda: runner.shutdown())

        self.assertEqual(result.launch_mode, "plan")
        self.assertEqual(result.total_steps, 2)

        wait_until(lambda: not runner.is_running, timeout_s=2.0)
        snapshot = runner.get_status_snapshot()
        self.assertFalse(snapshot["is_running"])
        self.assertTrue(snapshot["supports_hold_continue"])

        statuses = [event.get("current_step_status") for event in progress_events]
        self.assertIn("completed", statuses)

    def test_wait_state_step_succeeds_when_snapshot_matches(self):
        state = {"sequence": {"armed": False}}

        def state_snapshot():
            return state

        runner = ScriptRunner(state_snapshot_getter=state_snapshot)
        exit_payloads = []

        runner.start_script(
            {
                "name": "wait-state",
                "plan_steps": [
                    {
                        "type": "wait_state",
                        "path": "sequence.armed",
                        "equals": True,
                        "timeout_s": 1.0,
                        "poll_interval_s": 0.05,
                    }
                ],
            },
            script_id="script-2",
            on_exit=lambda payload: exit_payloads.append(dict(payload)),
        )
        self.addCleanup(lambda: runner.shutdown())

        time.sleep(0.15)
        state["sequence"]["armed"] = True

        wait_until(lambda: not runner.is_running, timeout_s=2.0)
        self.assertTrue(exit_payloads)
        self.assertEqual(exit_payloads[-1]["returncode"], 0)

    def test_wait_state_step_times_out_when_snapshot_never_matches(self):
        runner = ScriptRunner(state_snapshot_getter=lambda: {"sequence": {"armed": False}})
        exit_payloads = []

        runner.start_script(
            {
                "name": "wait-state-timeout",
                "plan_steps": [
                    {
                        "type": "wait_state",
                        "path": "sequence.armed",
                        "equals": True,
                        "timeout_s": 0.2,
                        "poll_interval_s": 0.05,
                    }
                ],
            },
            script_id="script-3",
            on_exit=lambda payload: exit_payloads.append(dict(payload)),
        )
        self.addCleanup(lambda: runner.shutdown())

        wait_until(lambda: not runner.is_running, timeout_s=2.0)
        self.assertTrue(exit_payloads)
        self.assertEqual(exit_payloads[-1]["returncode"], 1)
        self.assertIn("timed out", exit_payloads[-1]["error"])

    def test_stop_script_returns_plan_stop_result(self):
        runner = ScriptRunner()
        exit_payloads = []

        runner.start_script(
            {
                "name": "stoppable-plan",
                "plan_steps": [
                    {"type": "sleep", "seconds": 1.0},
                ],
            },
            script_id="script-4",
            on_exit=lambda payload: exit_payloads.append(dict(payload)),
        )

        result = runner.stop_script(reason="test_stop", timeout_s=1.0)
        self.addCleanup(lambda: runner.shutdown())

        self.assertEqual(result["reason"], "test_stop")
        self.assertTrue(result["supports_hold_continue"])
        self.assertIn(result["stopped_via"], {"plan_stop_flag", "plan_stop_timeout"})
