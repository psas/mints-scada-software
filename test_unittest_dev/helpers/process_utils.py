from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path


def list_matching_processes(matchers: list[str]) -> list[str]:
    if not matchers:
        return []
    result = subprocess.run(
        ["bash", "-lc", "ps -eo pid=,command="],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    lowered = [m.lower() for m in matchers]
    matches: list[str] = []
    for line in lines:
        lower_line = line.lower()
        if any(token in lower_line for token in lowered):
            matches.append(line)
    return matches


class AppSession:
    def __init__(self, cmd: str | None, working_dir: Path, stdout_path: Path):
        self.cmd = cmd
        self.working_dir = working_dir
        self.stdout_path = stdout_path
        self.process: subprocess.Popen[str] | None = None

    def start(self) -> None:
        if not self.cmd:
            return
        self.stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_handle = self.stdout_path.open("a", encoding="utf-8")
        self.process = subprocess.Popen(
            self.cmd,
            cwd=str(self.working_dir),
            shell=True,
            stdout=stdout_handle,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid,
        )

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def wait_until_ready(self, timeout: float, pattern: str | None = None) -> None:
        if self.process is None:
            return
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"Launch command exited early with code {self.process.returncode}. "
                    f"See {self.stdout_path}"
                )
            if pattern:
                try:
                    text = self.stdout_path.read_text(encoding="utf-8", errors="replace")
                except FileNotFoundError:
                    text = ""
                if pattern in text:
                    return
            else:
                # No explicit ready signal configured. A short settle period is the best
                # generic behavior without repo-specific hooks.
                time.sleep(min(timeout, 5.0))
                return
            time.sleep(0.5)
        if pattern:
            raise RuntimeError(
                f"Did not observe live-ready pattern {pattern!r} within {timeout}s. "
                f"See {self.stdout_path}"
            )

    def stop(self, timeout: float) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
        except Exception:
            try:
                self.process.terminate()
            except Exception:
                pass
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                return
            time.sleep(0.2)
        try:
            os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass
