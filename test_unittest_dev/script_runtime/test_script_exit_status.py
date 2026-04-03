from __future__ import annotations

import time
import unittest
from pathlib import Path
from typing import Any, Mapping

from backend.script_runner import ScriptRunner


class ScriptExitStatusTests(unittest.TestCase):
    """Tests for script exit classification and output forwarding."""

    PROJECT_ROOT = Path(__file__).resolve().parents[2]

    def _wait_until(self, predicate, timeout_s: float = 5.0) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail("Timed out waiting for condition")

    def test_successful_script_exits_with_returncode_zero(self) -> None:
        exits: list[dict[str, Any]] = []
        outputs: list[dict[str, Any]] = []

        runner = ScriptRunner(
            project_root=self.PROJECT_ROOT,
            output_callback=lambda info: outputs.append(dict(info)),
        )

        runner.start_script(
            {"name": "success", "inline_python": 'print("hello world")'},
            script_id="exit-ok",
            on_exit=lambda info: exits.append(dict(info)),
        )

        self._wait_until(lambda: len(exits) == 1)

        self.assertEqual(exits[0]["returncode"], 0)
        self.assertIsNone(exits[0].get("failure_message"))
        output_texts = [item["output_text"] for item in outputs]
        self.assertIn("hello world", output_texts)

    def test_script_with_exception_exits_with_failure_message(self) -> None:
        exits: list[dict[str, Any]] = []
        outputs: list[dict[str, Any]] = []

        runner = ScriptRunner(
            project_root=self.PROJECT_ROOT,
            output_callback=lambda info: outputs.append(dict(info)),
        )

        runner.start_script(
            {"name": "crash", "inline_python": 'raise ValueError("bad value")'},
            script_id="exit-fail",
            on_exit=lambda info: exits.append(dict(info)),
        )

        self._wait_until(lambda: len(exits) == 1)

        self.assertEqual(exits[0]["returncode"], 1)
        self.assertIn("ValueError", exits[0]["failure_message"])
        self.assertIn("bad value", exits[0]["failure_message"])

    def test_script_with_missing_device_exits_with_key_error(self) -> None:
        exits: list[dict[str, Any]] = []
        outputs: list[dict[str, Any]] = []

        runner = ScriptRunner(
            project_root=self.PROJECT_ROOT,
            state_snapshot_getter=lambda: {"device_registry": {"devices": []}},
            output_callback=lambda info: outputs.append(dict(info)),
        )

        runner.start_script(
            {"name": "bad-device", "inline_python": 'mints.devices["nonexistent"].open()'},
            script_id="exit-keyerr",
            on_exit=lambda info: exits.append(dict(info)),
        )

        self._wait_until(lambda: len(exits) == 1)

        self.assertEqual(exits[0]["returncode"], 1)
        self.assertIsNotNone(exits[0].get("failure_message"))
        self.assertIn("nonexistent", exits[0]["failure_message"])

    def test_stopped_script_has_operator_stop_reason(self) -> None:
        exits: list[dict[str, Any]] = []

        runner = ScriptRunner(
            project_root=self.PROJECT_ROOT,
            output_callback=lambda info: None,
        )

        runner.start_script(
            {"name": "long", "inline_python": 'wait(30.0)'},
            script_id="exit-stop",
            on_exit=lambda info: exits.append(dict(info)),
        )

        time.sleep(0.15)
        stop_result = runner.stop_script(reason="operator_stop", timeout_s=1.0)

        self.assertIn(stop_result["reason"], {"operator_stop"})
        self.assertIn(stop_result["stopped_via"], {"sigterm", "sigkill"})
        self.assertFalse(runner.is_running)

    def test_script_output_callback_receives_all_print_lines(self) -> None:
        exits: list[dict[str, Any]] = []
        outputs: list[dict[str, Any]] = []

        runner = ScriptRunner(
            project_root=self.PROJECT_ROOT,
            output_callback=lambda info: outputs.append(dict(info)),
        )

        script_text = '\n'.join([
            'print("line one")',
            'print("line two")',
            'print("line three")',
        ])

        runner.start_script(
            {"name": "multi-print", "inline_python": script_text},
            script_id="exit-multi",
            on_exit=lambda info: exits.append(dict(info)),
        )

        self._wait_until(lambda: len(exits) == 1)

        output_texts = [item["output_text"] for item in outputs]
        self.assertIn("line one", output_texts)
        self.assertIn("line two", output_texts)
        self.assertIn("line three", output_texts)
        self.assertEqual(exits[0]["returncode"], 0)


class StateStoreScriptOutputTests(unittest.TestCase):
    """Tests for script output and exit status stored in StateStore."""

    def test_append_script_output_stores_lines(self) -> None:
        from backend.state_store import StateStore
        store = StateStore(service_name="test", backend_started_at="2025-01-01T00:00:00.000Z")
        store.append_script_output("hello")
        store.append_script_output("world")
        snapshot = store.get_snapshot()
        self.assertEqual(snapshot["script_runner"]["output_lines"], ["hello", "world"])

    def test_append_script_output_caps_at_max_lines(self) -> None:
        from backend.state_store import StateStore
        store = StateStore(service_name="test", backend_started_at="2025-01-01T00:00:00.000Z")
        for i in range(510):
            store.append_script_output(f"line {i}")
        snapshot = store.get_snapshot()
        self.assertEqual(len(snapshot["script_runner"]["output_lines"]), 500)
        self.assertEqual(snapshot["script_runner"]["output_lines"][0], "line 10")

    def test_mark_script_finished_stores_exit_status_and_failure(self) -> None:
        from backend.state_store import StateStore
        store = StateStore(service_name="test", backend_started_at="2025-01-01T00:00:00.000Z")
        store.mark_script_finished(
            finished_wall_time="2025-01-01T00:00:00.000Z",
            return_code=1,
            reason="process_exit",
            failure_message="KeyError: 'bad-device'",
            exit_status="failed",
        )
        snapshot = store.get_snapshot()
        sr = snapshot["script_runner"]
        self.assertEqual(sr["last_exit_status"], "failed")
        self.assertEqual(sr["last_failure_message"], "KeyError: 'bad-device'")
        self.assertEqual(sr["last_exit_code"], 1)

    def test_mark_script_started_clears_previous_exit_info(self) -> None:
        from backend.state_store import StateStore
        store = StateStore(service_name="test", backend_started_at="2025-01-01T00:00:00.000Z")
        store.append_script_output("old output")
        store.mark_script_finished(
            finished_wall_time="2025-01-01T00:00:00.000Z",
            return_code=1,
            reason="process_exit",
            failure_message="SomeError",
            exit_status="failed",
        )

        store.mark_script_started(
            script_id="new-script",
            name="new",
            pid=1234,
            launch_mode="inline_python",
            command=["python", "-u", "host.py"],
            cwd="/tmp",
            started_wall_time="2025-01-01T00:01:00.000Z",
        )
        snapshot = store.get_snapshot()
        sr = snapshot["script_runner"]
        self.assertIsNone(sr["last_failure_message"])
        self.assertIsNone(sr["last_exit_status"])
        self.assertEqual(sr["output_lines"], [])


if __name__ == "__main__":
    unittest.main()
