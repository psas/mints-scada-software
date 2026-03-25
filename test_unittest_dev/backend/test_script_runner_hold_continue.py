from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip, wait_until


script_runner_module = import_module_or_skip("backend.script_runner")
ScriptRunner = script_runner_module.ScriptRunner


class TestScriptRunnerHoldContinue(unittest.TestCase):
    def test_hold_and_continue_round_trip_for_plan_script(self):
        progress_events = []
        runner = ScriptRunner(progress_callback=lambda payload: progress_events.append(dict(payload)))
        self.addCleanup(lambda: runner.shutdown())

        runner.start_script(
            {
                "name": "holdable-plan",
                "plan_steps": [
                    {"type": "sleep", "seconds": 0.35},
                    {"type": "note", "message": "after hold"},
                ],
            },
            script_id="script-hold-1",
            on_exit=lambda payload: None,
        )

        hold_result = runner.hold_script()
        self.assertIn(hold_result["status"], {"hold_requested", "held"})

        wait_until(
            lambda: runner.get_status_snapshot().get("is_held") is True,
            timeout_s=2.0,
            message="Plan runner never entered held state",
        )

        snapshot = runner.get_status_snapshot()
        self.assertTrue(snapshot["is_running"])
        self.assertTrue(snapshot["is_held"])
        self.assertTrue(snapshot["hold_requested"])

        continue_result = runner.continue_script()
        self.assertEqual(continue_result["status"], "continued")
        self.assertFalse(continue_result["is_held"])
        self.assertFalse(continue_result["hold_requested"])

        wait_until(lambda: not runner.is_running, timeout_s=2.0)
        statuses = [event.get("current_step_status") for event in progress_events]
        self.assertIn("held", statuses)

    def test_continue_without_hold_raises(self):
        runner = ScriptRunner()
        self.addCleanup(lambda: runner.shutdown())

        runner.start_script(
            {
                "name": "no-hold-yet",
                "plan_steps": [{"type": "sleep", "seconds": 0.05}],
            },
            script_id="script-hold-2",
            on_exit=lambda payload: None,
        )
        with self.assertRaises(RuntimeError):
            runner.continue_script()

        wait_until(lambda: not runner.is_running, timeout_s=2.0)

    def test_hold_requires_running_plan_script(self):
        runner = ScriptRunner()
        self.addCleanup(lambda: runner.shutdown())

        with self.assertRaises(RuntimeError):
            runner.hold_script()
