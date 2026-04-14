"""Smoke tests for Makefile / bootstrap workflow commands.

These run real make targets as subprocesses and verify basic behavior:
exit codes, output sanity, confirmation gates.  They do NOT require
hardware or a running application.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_make(target: str, *, stdin: str | None = None, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run a make target and return the completed process."""
    import os
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["make", target],
        cwd=str(REPO_ROOT),
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


class TestMakeHelp(unittest.TestCase):
    def test_help_exits_zero(self):
        result = _run_make("help")
        self.assertEqual(result.returncode, 0)

    def test_help_shows_key_commands(self):
        result = _run_make("help")
        for cmd in ("make setup", "make run", "make stop", "make clean"):
            with self.subTest(cmd=cmd):
                self.assertIn(cmd, result.stdout)


class TestMakeStopIdempotent(unittest.TestCase):
    def test_stop_exits_zero_when_nothing_running(self):
        result = _run_make("stop")
        self.assertEqual(result.returncode, 0)
        self.assertIn("No running application processes found", result.stdout)


class TestMakeCleanDev(unittest.TestCase):
    def test_clean_dev_exits_zero(self):
        result = _run_make("_clean-dev")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Runtime artifacts cleaned", result.stdout)


class TestCleanHistoryConfirmation(unittest.TestCase):
    def test_cancel_returns_nonzero(self):
        result = _run_make("clean-history", stdin="cancel\n")
        self.assertNotEqual(result.returncode, 0, "Cancelling should return non-zero")
        self.assertIn("Cancelled", result.stdout)

    def test_force_skips_confirmation(self):
        result = _run_make("clean-history", env_extra={"MINTS_FORCE": "1"})
        self.assertEqual(result.returncode, 0)


class TestCleanConfirmation(unittest.TestCase):
    def test_cancel_returns_nonzero(self):
        result = _run_make("clean", stdin="cancel\n")
        self.assertNotEqual(result.returncode, 0, "Cancelling should return non-zero")
        self.assertIn("Cancelled", result.stdout)


if __name__ == "__main__":
    unittest.main()
