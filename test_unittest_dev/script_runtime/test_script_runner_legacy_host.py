from __future__ import annotations

import time
import unittest
from pathlib import Path
from typing import Any, Mapping

from backend.script_runner import ScriptRunner


class ScriptRunnerLegacyHostTests(unittest.TestCase):
    def _wait_until(self, predicate, timeout_s: float = 5.0) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail("Timed out waiting for condition")

    def test_legacy_inline_script_routes_print_wait_and_device_commands(self) -> None:
        command_calls: list[dict[str, Any]] = []
        outputs: list[dict[str, Any]] = []
        exits: list[dict[str, Any]] = []

        def command_dispatcher(payload: Mapping[str, Any]) -> dict[str, Any]:
            command_calls.append(dict(payload))
            return {"success": True}

        runner = ScriptRunner(
            project_root=Path(__file__).resolve().parents[2],
            command_dispatcher=command_dispatcher,
            state_snapshot_getter=lambda: {
                "device_registry": {
                    "devices": [
                        {"id": "eng_purge"},
                    ]
                }
            },
            output_callback=lambda info: outputs.append(dict(info)),
        )

        script_text = '\n'.join([
            'print("Click click time!")',
            'mints.devices["eng_purge"].open()',
            'wait(0.05)',
            'mints.devices["eng_purge"].close()',
            'print("Done clicking")',
        ])

        result = runner.start_script(
            {"name": "legacy-inline", "inline_python": script_text},
            script_id="script-1",
            on_exit=lambda info: exits.append(dict(info)),
        )
        self.assertEqual(result.launch_mode, "inline_python")
        self.assertGreater(result.pid, 0)

        self._wait_until(lambda: len(exits) == 1)

        self.assertEqual(command_calls[0]["command_name"], "open")
        self.assertEqual(command_calls[0]["device_id"], "eng_purge")
        self.assertEqual(command_calls[1]["command_name"], "close")
        self.assertEqual(command_calls[1]["device_id"], "eng_purge")
        self.assertIn("Click click time!", [item["output_text"] for item in outputs])
        self.assertIn("Done clicking", [item["output_text"] for item in outputs])
        self.assertEqual(exits[0]["returncode"], 0)
        self.assertFalse(runner.is_running)

    def test_legacy_inline_script_abort_uses_abort_dispatcher(self) -> None:
        abort_calls: list[dict[str, Any]] = []
        exits: list[dict[str, Any]] = []

        def abort_dispatcher(payload: Mapping[str, Any]) -> dict[str, Any]:
            abort_calls.append(dict(payload))
            return {"success": True, "command_name": "abort"}

        runner = ScriptRunner(
            project_root=Path(__file__).resolve().parents[2],
            abort_dispatcher=abort_dispatcher,
            output_callback=lambda info: None,
        )

        result = runner.start_script(
            {"name": "legacy-abort", "inline_python": 'abort("boom")'},
            script_id="script-2",
            on_exit=lambda info: exits.append(dict(info)),
        )
        self.assertEqual(result.launch_mode, "inline_python")

        self._wait_until(lambda: len(exits) == 1)
        self.assertEqual(abort_calls[0]["command_name"], "abort")
        self.assertEqual(abort_calls[0]["message"], "boom")
        self.assertEqual(exits[0]["returncode"], 0)

    def test_stop_script_terminates_stuck_legacy_host_without_hanging(self) -> None:
        exits: list[dict[str, Any]] = []
        runner = ScriptRunner(
            project_root=Path(__file__).resolve().parents[2],
            output_callback=lambda info: None,
        )

        runner.start_script(
            {"name": "stuck", "inline_python": 'print("start"); wait(5.0)'},
            script_id="script-3",
            on_exit=lambda info: exits.append(dict(info)),
        )

        time.sleep(0.15)
        stop_result = runner.stop_script(reason="operator_stop", timeout_s=1.0)
        self.assertIn(stop_result["stopped_via"], {"sigterm", "sigkill"})
        self.assertFalse(runner.is_running)


if __name__ == "__main__":
    unittest.main()
