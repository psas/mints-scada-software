# backend/script_runner.py

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from scripts.script_runtime.script_protocol import (
    SCRIPT_HOST_MESSAGE_ABORT_REQUEST,
    SCRIPT_HOST_MESSAGE_COMMAND_REQUEST,
    SCRIPT_HOST_MESSAGE_SCRIPT_EXIT,
    SCRIPT_HOST_MESSAGE_SCRIPT_OUTPUT,
)
from scripts.script_runtime.script_proxy import ScriptHostProxy


log = logging.getLogger(__name__)


@dataclass
class ScriptStartResult:
    script_id: str
    name: str
    pid: int
    launch_mode: str
    command: list[str]
    cwd: str | None
    current_step_index: int | None = None
    total_steps: int | None = None
    current_step_name: str | None = None
    current_step_type: str | None = None
    current_step_status: str | None = None
    plan_steps_summary: list[str] = field(default_factory=list)


class ScriptRunner:
    """Backend-owned script runner.

    Supported start payload shapes:
    - {"name": "...", "command": ["python3", "script.py", ...], "cwd": "...", "env": {...}}
    - {"name": "...", "inline_python": "print('hello')", "cwd": "...", "env": {...}}
    - {"name": "...", "plan_steps": [...]}  # backend-native plan mode

    Current scope:
    - single running script at a time
    - subprocess lifecycle ownership in backend for legacy mode
    - background thread ownership in backend for plan mode
    - hold/continue semantics for plan mode only
    - cooperative pause points for sleep / wait_state / note / pre-dispatch checkpoints
    """

    def __init__(
        self,
        *,
        command_dispatcher: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
        state_snapshot_getter: Callable[[], Mapping[str, Any]] | None = None,
        progress_callback: Callable[[Mapping[str, Any]], None] | None = None,
        abort_dispatcher: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
        output_callback: Callable[[Mapping[str, Any]], None] | None = None,
        project_root: str | Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._plan_thread: threading.Thread | None = None
        self._plan_stop = threading.Event()
        self._plan_hold_requested = threading.Event()
        self._plan_resume = threading.Event()
        self._script_id: str | None = None
        self._script_name: str | None = None
        self._launch_mode: str | None = None
        self._command: list[str] = []
        self._cwd: str | None = None
        self._watcher_thread: threading.Thread | None = None
        self._stop_watcher = threading.Event()
        self._on_exit: Callable[[Mapping[str, Any]], None] | None = None
        self._command_dispatcher = command_dispatcher
        self._abort_dispatcher = abort_dispatcher or command_dispatcher
        self._state_snapshot_getter = state_snapshot_getter
        self._progress_callback = progress_callback
        self._output_callback = output_callback
        self._project_root = Path(project_root).expanduser().resolve() if project_root else Path.cwd().resolve()
        self._host_proxy: ScriptHostProxy | None = None
        self._captured_output_lines: list[str] = []
        self._total_steps: int | None = None
        self._current_step_index: int | None = None
        self._current_step_name: str | None = None
        self._current_step_type: str | None = None
        self._current_step_status: str | None = None
        self._plan_steps_summary: list[str] = []
        self._is_held = False

    @property
    def is_running(self) -> bool:
        with self._lock:
            process_running = self._process is not None and self._process.poll() is None
            plan_running = self._plan_thread is not None and self._plan_thread.is_alive()
            return process_running or plan_running

    def get_status_snapshot(self) -> dict[str, Any]:
        snapshot = self._script_progress_snapshot()
        snapshot["is_running"] = self.is_running
        snapshot["supports_hold_continue"] = bool(snapshot.get("launch_mode") == "plan")
        return snapshot

    def start_script(
        self,
        payload: Mapping[str, Any],
        *,
        script_id: str,
        on_exit,
    ) -> ScriptStartResult:
        with self._lock:
            if self.is_running:
                raise RuntimeError("A backend-owned script is already running")

            name = self._require_non_empty_string(payload, "name")
            cwd = self._get_optional_string(payload, "cwd")

            if "plan_steps" in payload:
                return self._start_plan_script(
                    payload,
                    script_id=script_id,
                    name=name,
                    cwd=cwd,
                    on_exit=on_exit,
                )

            if "inline_python" in payload:
                return self._start_legacy_host_script(
                    payload,
                    script_id=script_id,
                    name=name,
                    cwd=cwd,
                    on_exit=on_exit,
                )

            return self._start_subprocess_script(
                payload,
                script_id=script_id,
                name=name,
                cwd=cwd,
                on_exit=on_exit,
            )

    def stop_script(self, *, reason: str = "operator_stop", timeout_s: float = 3.0) -> dict[str, Any]:
        log.info("stop_script requested: reason=%r, timeout_s=%s", reason, timeout_s)
        with self._lock:
            launch_mode = self._launch_mode
            if launch_mode == "plan":
                if self._plan_thread is None or not self._plan_thread.is_alive():
                    raise RuntimeError("No running backend-owned script to stop")

                script_id = self._script_id
                script_name = self._script_name
                pid = os.getpid()
                log.info("Stopping plan-mode script %r (id=%s, reason=%r)", script_name, script_id, reason)
                self._stop_watcher.set()
                self._plan_stop.set()
                self._plan_resume.set()
                plan_thread = self._plan_thread
            else:
                if self._process is None or self._process.poll() is not None:
                    raise RuntimeError("No running backend-owned script to stop")

                process = self._process
                script_id = self._script_id
                script_name = self._script_name
                pid = process.pid
                log.info("Stopping subprocess script %r (id=%s, pid=%s, reason=%r)", script_name, script_id, pid, reason)

        if launch_mode == "plan":
            assert plan_thread is not None
            plan_thread.join(timeout=timeout_s)
            if plan_thread.is_alive():
                stopped_via = "plan_stop_timeout"
                return_code = 1
            else:
                stopped_via = "plan_stop_flag"
                return_code = 0
            self._clear_after_exit()
            return {
                "script_id": script_id,
                "name": script_name,
                "pid": pid,
                "reason": reason,
                "returncode": return_code,
                "stopped_via": stopped_via,
                "supports_hold_continue": True,
            }

        assert self._process is not None
        process = self._process
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

        try:
            return_code = process.wait(timeout=timeout_s)
            stopped_via = "sigterm"
        except subprocess.TimeoutExpired:
            log.warning("Script pid=%s did not exit after SIGTERM (%.1fs); escalating to SIGKILL", process.pid, timeout_s)
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return_code = process.wait(timeout=1.0)
            stopped_via = "sigkill"

        log.info("Script stopped: pid=%s, stopped_via=%s, returncode=%s, reason=%r", process.pid, stopped_via, return_code, reason)
        self._stop_watcher.set()
        host_proxy = None
        with self._lock:
            host_proxy = self._host_proxy
        if host_proxy is not None:
            try:
                host_proxy.close()
            except Exception:
                pass
        self._clear_after_exit()

        return {
            "script_id": script_id,
            "name": script_name,
            "pid": pid,
            "reason": reason,
            "returncode": return_code,
            "stopped_via": stopped_via,
            "supports_hold_continue": False,
        }

    def hold_script(self, *, reason: str = "operator_hold") -> dict[str, Any]:
        del reason
        with self._lock:
            if not self.is_running:
                raise RuntimeError("No running backend-owned script to hold")
            if self._launch_mode != "plan":
                raise RuntimeError("Hold is only supported for backend plan-mode scripts")

            self._plan_hold_requested.set()
            self._plan_resume.clear()

            if self._is_held:
                status = "held"
            else:
                status = "hold_requested"

            return self._build_plan_control_result(status=status)

    def continue_script(self, *, reason: str = "operator_continue") -> dict[str, Any]:
        del reason
        with self._lock:
            if not self.is_running:
                raise RuntimeError("No running backend-owned script to continue")
            if self._launch_mode != "plan":
                raise RuntimeError("Continue is only supported for backend plan-mode scripts")
            if not self._plan_hold_requested.is_set() and not self._is_held:
                raise RuntimeError("Backend plan-mode script is not currently held")

            self._plan_hold_requested.clear()
            self._is_held = False
            self._plan_resume.set()
            result = self._build_plan_control_result(status="continued")
            result["is_held"] = False
            result["hold_requested"] = False
            return result

    def shutdown(self) -> None:
        with self._lock:
            running = self.is_running
        if running:
            log.info("ScriptRunner.shutdown(): stopping running script (reason=backend_shutdown)")
            try:
                self.stop_script(reason="backend_shutdown")
            except Exception:
                log.exception("ScriptRunner.shutdown(): stop_script failed")

    def _start_legacy_host_script(
        self,
        payload: Mapping[str, Any],
        *,
        script_id: str,
        name: str,
        cwd: str | None,
        on_exit,
    ) -> ScriptStartResult:
        script_text = payload.get("inline_python")
        if not isinstance(script_text, str) or not script_text.strip():
            raise ValueError("'inline_python' must be a non-empty string")

        resolved_cwd = cwd or str(self._project_root)
        host_proxy = ScriptHostProxy(project_root=self._project_root)
        host_ready = host_proxy.start(script_path=payload.get("script_path"), cwd=resolved_cwd)
        host_pid = host_ready.get("payload", {}).get("pid")

        execute_started = host_proxy.execute_legacy_script(
            script_text=script_text,
            device_ids=self._build_legacy_device_ids(),
            timeout_s=3.0,
        )

        process = host_proxy.process
        if process is None:
            raise RuntimeError("Legacy script host did not stay running after execute_started")

        self._process = process
        self._host_proxy = host_proxy
        self._plan_thread = None
        self._script_id = script_id
        self._script_name = name
        self._launch_mode = "inline_python"
        self._command = [self.python_executable if hasattr(self, "python_executable") else sys.executable, "-u", str(self._project_root / "scripts" / "script_runtime" / "script_host.py")]
        self._cwd = resolved_cwd
        self._on_exit = on_exit
        self._total_steps = None
        self._current_step_index = None
        self._current_step_name = None
        self._current_step_type = None
        self._current_step_status = None
        self._plan_steps_summary = []
        self._is_held = False
        self._captured_output_lines = []

        self._stop_watcher.clear()
        self._watcher_thread = threading.Thread(
            target=self._watch_host_process,
            name=f"backend-script-host-watcher-{script_id[:8]}",
            daemon=True,
        )
        self._watcher_thread.start()

        return ScriptStartResult(
            script_id=script_id,
            name=name,
            pid=int(host_pid) if isinstance(host_pid, int) else process.pid,
            launch_mode=self._launch_mode,
            command=list(self._command),
            cwd=resolved_cwd,
        )

    def _start_subprocess_script(
        self,
        payload: Mapping[str, Any],
        *,
        script_id: str,
        name: str,
        cwd: str | None,
        on_exit,
    ) -> ScriptStartResult:
        env_overrides = self._get_optional_string_mapping(payload, "env") or {}
        command = self._build_command(payload)
        if not command:
            raise ValueError("Script start payload must define either 'command', 'inline_python', or 'plan_steps'")

        merged_env = os.environ.copy()
        merged_env.update(env_overrides)

        process = subprocess.Popen(
            command,
            cwd=cwd or None,
            env=merged_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )

        self._process = process
        self._plan_thread = None
        self._script_id = script_id
        self._script_name = name
        self._launch_mode = "inline_python" if "inline_python" in payload else "command"
        self._command = list(command)
        self._cwd = cwd
        self._on_exit = on_exit
        self._total_steps = None
        self._current_step_index = None
        self._current_step_name = None
        self._current_step_type = None
        self._current_step_status = None
        self._plan_steps_summary = []
        self._is_held = False

        self._stop_watcher.clear()
        self._watcher_thread = threading.Thread(
            target=self._watch_process,
            name=f"backend-script-watcher-{script_id[:8]}",
            daemon=True,
        )
        self._watcher_thread.start()

        return ScriptStartResult(
            script_id=script_id,
            name=name,
            pid=process.pid,
            launch_mode=self._launch_mode,
            command=list(command),
            cwd=cwd,
        )

    def _start_plan_script(
        self,
        payload: Mapping[str, Any],
        *,
        script_id: str,
        name: str,
        cwd: str | None,
        on_exit,
    ) -> ScriptStartResult:
        plan_steps = self._normalize_plan_steps(payload.get("plan_steps"))
        if not plan_steps:
            raise ValueError("'plan_steps' must be a non-empty list")

        self._process = None
        self._plan_thread = None
        self._plan_stop.clear()
        self._plan_hold_requested.clear()
        self._plan_resume.clear()
        self._is_held = False
        self._stop_watcher.clear()
        self._script_id = script_id
        self._script_name = name
        self._launch_mode = "plan"
        self._command = [f"plan:{len(plan_steps)} steps"]
        self._cwd = cwd
        self._on_exit = on_exit
        self._total_steps = len(plan_steps)
        self._current_step_index = 0
        self._current_step_name = None
        self._current_step_type = None
        self._current_step_status = "starting"
        self._plan_steps_summary = [self._summarize_step(i + 1, step) for i, step in enumerate(plan_steps)]

        self._plan_thread = threading.Thread(
            target=self._run_plan_thread,
            args=(plan_steps,),
            name=f"backend-plan-runner-{script_id[:8]}",
            daemon=True,
        )
        self._plan_thread.start()

        return ScriptStartResult(
            script_id=script_id,
            name=name,
            pid=os.getpid(),
            launch_mode="plan",
            command=list(self._command),
            cwd=cwd,
            current_step_index=0,
            total_steps=len(plan_steps),
            current_step_name=None,
            current_step_type=None,
            current_step_status="starting",
            plan_steps_summary=list(self._plan_steps_summary),
        )

    def _run_plan_thread(self, plan_steps: list[dict[str, Any]]) -> None:
        with self._lock:
            script_id = self._script_id
            script_name = self._script_name
            launch_mode = self._launch_mode
            command = list(self._command)
            cwd = self._cwd
            on_exit = self._on_exit
            total_steps = self._total_steps or len(plan_steps)
            plan_steps_summary = list(self._plan_steps_summary)

        return_code = 0
        failure_message: str | None = None

        try:
            for index, step in enumerate(plan_steps, start=1):
                if self._plan_stop.is_set():
                    return_code = 0
                    break

                step_name = self._get_step_name(step, index)
                step_type = self._require_step_type(step)
                self._emit_progress(
                    current_step_index=index,
                    total_steps=total_steps,
                    current_step_name=step_name,
                    current_step_type=step_type,
                    current_step_status="running",
                    plan_steps_summary=plan_steps_summary,
                )

                self._honor_hold_point(
                    current_step_index=index,
                    total_steps=total_steps,
                    current_step_name=step_name,
                    current_step_type=step_type,
                    current_step_status="hold_requested",
                    plan_steps_summary=plan_steps_summary,
                )

                self._execute_plan_step(
                    step_type,
                    step,
                    current_step_index=index,
                    total_steps=total_steps,
                    current_step_name=step_name,
                    plan_steps_summary=plan_steps_summary,
                )

                if self._plan_stop.is_set():
                    return_code = 0
                    break

                self._emit_progress(
                    current_step_index=index,
                    total_steps=total_steps,
                    current_step_name=step_name,
                    current_step_type=step_type,
                    current_step_status="completed",
                    plan_steps_summary=plan_steps_summary,
                )

            else:
                self._emit_progress(
                    current_step_index=total_steps,
                    total_steps=total_steps,
                    current_step_name="plan_complete",
                    current_step_type="complete",
                    current_step_status="completed",
                    plan_steps_summary=plan_steps_summary,
                )
        except Exception as exc:
            return_code = 1
            failure_message = str(exc)
            self._emit_progress(
                current_step_index=self._current_step_index,
                total_steps=total_steps,
                current_step_name=self._current_step_name,
                current_step_type=self._current_step_type,
                current_step_status="failed",
                plan_steps_summary=plan_steps_summary,
            )

        if self._stop_watcher.is_set():
            return

        exit_snapshot = self._script_progress_snapshot()
        self._clear_after_exit()
        if callable(on_exit):
            payload = {
                "script_id": script_id,
                "name": script_name,
                "pid": os.getpid(),
                "launch_mode": launch_mode,
                "command": command,
                "cwd": cwd,
                "returncode": return_code,
                "current_step_index": exit_snapshot.get("current_step_index"),
                "total_steps": exit_snapshot.get("total_steps"),
                "current_step_name": exit_snapshot.get("current_step_name"),
                "current_step_type": exit_snapshot.get("current_step_type"),
                "current_step_status": exit_snapshot.get("current_step_status"),
                "plan_steps_summary": exit_snapshot.get("plan_steps_summary", []),
            }
            if failure_message is not None:
                payload["failure_message"] = failure_message
            on_exit(payload)

    def _execute_plan_step(
        self,
        step_type: str,
        step: Mapping[str, Any],
        *,
        current_step_index: int,
        total_steps: int,
        current_step_name: str,
        plan_steps_summary: list[str],
    ) -> None:
        if step_type == "sleep":
            seconds = self._coerce_positive_number(step.get("seconds"), key="seconds")
            self._sleep_interruptibly(
                seconds,
                current_step_index=current_step_index,
                total_steps=total_steps,
                current_step_name=current_step_name,
                current_step_type=step_type,
                plan_steps_summary=plan_steps_summary,
            )
            return

        if step_type == "note":
            _ = self._require_non_empty_step_string(step, "message")
            self._honor_hold_point(
                current_step_index=current_step_index,
                total_steps=total_steps,
                current_step_name=current_step_name,
                current_step_type=step_type,
                current_step_status="hold_requested",
                plan_steps_summary=plan_steps_summary,
            )
            return

        if step_type == "command_request":
            if self._command_dispatcher is None:
                raise RuntimeError("Plan-mode command_request step requires a command dispatcher callback")
            payload = step.get("payload")
            if not isinstance(payload, Mapping):
                raise ValueError("Plan-mode command_request step must include an object 'payload'")
            self._honor_hold_point(
                current_step_index=current_step_index,
                total_steps=total_steps,
                current_step_name=current_step_name,
                current_step_type=step_type,
                current_step_status="hold_requested",
                plan_steps_summary=plan_steps_summary,
            )
            result = self._command_dispatcher(dict(payload))
            if not bool(result.get("success")):
                raise RuntimeError(result.get("error") or "Plan command step failed")
            return

        if step_type == "wait_state":
            if self._state_snapshot_getter is None:
                raise RuntimeError("Plan-mode wait_state step requires a state snapshot callback")
            path = self._require_non_empty_step_string(step, "path")
            timeout_s = float(step.get("timeout_s", 30.0))
            poll_interval_s = float(step.get("poll_interval_s", 0.25))
            expected = step.get("equals", True)
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                if self._plan_stop.is_set():
                    return
                self._honor_hold_point(
                    current_step_index=current_step_index,
                    total_steps=total_steps,
                    current_step_name=current_step_name,
                    current_step_type=step_type,
                    current_step_status="hold_requested",
                    plan_steps_summary=plan_steps_summary,
                )
                snapshot = self._state_snapshot_getter()
                actual = self._lookup_state_path(snapshot, path)
                if actual == expected:
                    return
                time.sleep(max(0.05, poll_interval_s))
            raise TimeoutError(f"Plan wait_state step timed out waiting for {path!r} == {expected!r}")

        if step_type == "fail":
            message = self._get_optional_step_string(step, "message") or "Plan requested failure"
            raise RuntimeError(message)

        raise ValueError(f"Unsupported plan step type: {step_type}")

    def _emit_progress(
        self,
        *,
        current_step_index: int | None,
        total_steps: int | None,
        current_step_name: str | None,
        current_step_type: str | None,
        current_step_status: str | None,
        plan_steps_summary: list[str],
        is_held: bool | None = None,
        hold_requested: bool | None = None,
    ) -> None:
        with self._lock:
            self._current_step_index = current_step_index
            self._current_step_name = current_step_name
            self._current_step_type = current_step_type
            self._current_step_status = current_step_status
            if is_held is None:
                is_held = self._is_held
            else:
                self._is_held = bool(is_held)
            if hold_requested is None:
                hold_requested = self._plan_hold_requested.is_set()
            payload = {
                "script_id": self._script_id,
                "name": self._script_name,
                "pid": self._process.pid if self._process is not None else os.getpid(),
                "launch_mode": self._launch_mode,
                "command": list(self._command),
                "cwd": self._cwd,
                "current_step_index": current_step_index,
                "total_steps": total_steps,
                "current_step_name": current_step_name,
                "current_step_type": current_step_type,
                "current_step_status": current_step_status,
                "plan_steps_summary": list(plan_steps_summary),
                "is_held": bool(is_held),
                "hold_requested": bool(hold_requested),
                "progress_wall_time": self._utc_now_iso(),
            }
        if callable(self._progress_callback):
            self._progress_callback(payload)

    def _watch_host_process(self) -> None:
        with self._lock:
            host_proxy = self._host_proxy
            process = self._process
            script_id = self._script_id
            script_name = self._script_name
            launch_mode = self._launch_mode
            command = list(self._command)
            cwd = self._cwd
            on_exit = self._on_exit

        if host_proxy is None or process is None:
            return

        exit_payload: dict[str, Any] | None = None

        while True:
            if self._stop_watcher.is_set():
                return

            try:
                message = host_proxy.read_next_message(timeout_s=0.20)
            except TimeoutError:
                if process.poll() is not None:
                    break
                continue

            message_type = message.get("type")
            payload = message.get("payload")
            if not isinstance(payload, Mapping):
                payload = {}

            if message_type == SCRIPT_HOST_MESSAGE_SCRIPT_OUTPUT:
                self._handle_host_output(payload)
                continue

            if message_type == SCRIPT_HOST_MESSAGE_COMMAND_REQUEST:
                self._handle_host_command_request(payload)
                continue

            if message_type == SCRIPT_HOST_MESSAGE_ABORT_REQUEST:
                self._handle_host_abort_request(payload)
                continue

            if message_type == SCRIPT_HOST_MESSAGE_SCRIPT_EXIT:
                exit_payload = {
                    "script_id": script_id,
                    "name": script_name,
                    "pid": process.pid,
                    "launch_mode": launch_mode,
                    "command": command,
                    "cwd": cwd,
                    "returncode": payload.get("returncode"),
                }
                if isinstance(payload.get("failure_message"), str) and payload.get("failure_message"):
                    exit_payload["failure_message"] = payload.get("failure_message")
                break

        try:
            if host_proxy.is_running:
                host_proxy.shutdown(timeout_s=1.0)
            else:
                host_proxy.close()
        except Exception:
            try:
                host_proxy.terminate()
            except Exception:
                pass

        if self._stop_watcher.is_set():
            return

        if exit_payload is None:
            return_code = process.poll()
            exit_payload = {
                "script_id": script_id,
                "name": script_name,
                "pid": process.pid,
                "launch_mode": launch_mode,
                "command": command,
                "cwd": cwd,
                "returncode": return_code,
            }

        self._clear_after_exit()

        if callable(on_exit):
            on_exit(exit_payload)

    def _handle_host_output(self, payload: Mapping[str, Any]) -> None:
        text = payload.get("text")
        if not isinstance(text, str):
            return
        with self._lock:
            self._captured_output_lines.append(text)
            callback = self._output_callback
            info = {
                "script_id": self._script_id,
                "name": self._script_name,
                "pid": self._process.pid if self._process is not None else None,
                "launch_mode": self._launch_mode,
                "output_text": text,
                "output_level": payload.get("level") if isinstance(payload.get("level"), str) else "info",
                "progress_wall_time": payload.get("wall_time") if isinstance(payload.get("wall_time"), str) else self._utc_now_iso(),
            }
        if callable(callback):
            callback(info)

    def _handle_host_command_request(self, payload: Mapping[str, Any]) -> None:
        if self._command_dispatcher is None:
            return
        try:
            self._command_dispatcher(dict(payload))
        except Exception:
            log.exception("Script host command request failed")

    def _handle_host_abort_request(self, payload: Mapping[str, Any]) -> None:
        dispatcher = self._abort_dispatcher or self._command_dispatcher
        if dispatcher is None:
            return
        try:
            dispatcher(dict(payload))
        except Exception:
            log.exception("Script host abort request failed")

    def _watch_process(self) -> None:
        with self._lock:
            process = self._process
            script_id = self._script_id
            script_name = self._script_name
            launch_mode = self._launch_mode
            command = list(self._command)
            cwd = self._cwd
            on_exit = self._on_exit

        if process is None:
            return

        return_code = process.wait()

        if self._stop_watcher.is_set():
            return

        self._clear_after_exit()

        if callable(on_exit):
            on_exit(
                {
                    "script_id": script_id,
                    "name": script_name,
                    "pid": process.pid,
                    "launch_mode": launch_mode,
                    "command": command,
                    "cwd": cwd,
                    "returncode": return_code,
                }
            )

    def _clear_after_exit(self) -> None:
        with self._lock:
            self._process = None
            self._host_proxy = None
            self._plan_thread = None
            self._script_id = None
            self._script_name = None
            self._launch_mode = None
            self._command = []
            self._cwd = None
            self._on_exit = None
            self._total_steps = None
            self._current_step_index = None
            self._current_step_name = None
            self._current_step_type = None
            self._current_step_status = None
            self._plan_steps_summary = []
            self._captured_output_lines = []
            self._is_held = False
            self._plan_stop.clear()
            self._plan_hold_requested.clear()
            self._plan_resume.clear()

    def _build_command(self, payload: Mapping[str, Any]) -> list[str]:
        if "command" in payload:
            value = payload["command"]
            if not isinstance(value, list) or not value:
                raise ValueError("'command' must be a non-empty list of strings")
            command: list[str] = []
            for item in value:
                if not isinstance(item, str) or not item.strip():
                    raise ValueError("'command' list entries must be non-empty strings")
                command.append(item)
            return command

        if "inline_python" in payload:
            code = payload["inline_python"]
            if not isinstance(code, str) or not code.strip():
                raise ValueError("'inline_python' must be a non-empty string")
            return [sys.executable, "-u", str(self._project_root / "scripts" / "script_runtime" / "script_host.py")]

        return []

    def _build_legacy_device_ids(self) -> list[str]:
        if self._state_snapshot_getter is None:
            return []
        try:
            snapshot = self._state_snapshot_getter()
        except Exception:
            return []
        if not isinstance(snapshot, Mapping):
            return []
        registry = snapshot.get("device_registry")
        if not isinstance(registry, Mapping):
            return []
        devices = registry.get("devices")
        if not isinstance(devices, list):
            return []
        result: list[str] = []
        for item in devices:
            if not isinstance(item, Mapping):
                continue
            device_id = item.get("id")
            if isinstance(device_id, str) and device_id.strip():
                result.append(device_id.strip())
        return result

    def _normalize_plan_steps(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list) or not value:
            raise ValueError("'plan_steps' must be a non-empty list")
        result: list[dict[str, Any]] = []
        for index, item in enumerate(value, start=1):
            if not isinstance(item, Mapping):
                raise ValueError(f"Plan step #{index} must be an object")
            step = dict(item)
            self._require_step_type(step)
            result.append(step)
        return result

    def _require_non_empty_string(self, payload: Mapping[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Script payload must include a non-empty string '{key}'")
        return value.strip()

    def _get_optional_string(self, payload: Mapping[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"Script payload field '{key}' must be a string when provided")
        stripped = value.strip()
        return stripped or None

    def _get_optional_string_mapping(
        self,
        payload: Mapping[str, Any],
        key: str,
    ) -> dict[str, str] | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError(f"Script payload field '{key}' must be an object when provided")

        result: dict[str, str] = {}
        for env_key, env_value in value.items():
            if not isinstance(env_key, str):
                raise ValueError(f"Script env key {env_key!r} must be a string")
            if not isinstance(env_value, str):
                raise ValueError(f"Script env value for {env_key!r} must be a string")
            result[env_key] = env_value
        return result

    def _require_step_type(self, step: Mapping[str, Any]) -> str:
        value = step.get("type")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Each plan step must include a non-empty string 'type'")
        return value.strip()

    def _get_step_name(self, step: Mapping[str, Any], index: int) -> str:
        name = step.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        return f"step_{index:02d}_{self._require_step_type(step)}"

    def _get_optional_step_string(self, step: Mapping[str, Any], key: str) -> str | None:
        value = step.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"Plan step field '{key}' must be a string when provided")
        stripped = value.strip()
        return stripped or None

    def _require_non_empty_step_string(self, step: Mapping[str, Any], key: str) -> str:
        value = self._get_optional_step_string(step, key)
        if not value:
            raise ValueError(f"Plan step must include a non-empty string '{key}'")
        return value

    def _coerce_positive_number(self, value: Any, *, key: str) -> float:
        if not isinstance(value, (int, float)):
            raise ValueError(f"Plan step field '{key}' must be a number")
        converted = float(value)
        if converted < 0.0:
            raise ValueError(f"Plan step field '{key}' must be non-negative")
        return converted

    def _sleep_interruptibly(
        self,
        seconds: float,
        *,
        current_step_index: int,
        total_steps: int,
        current_step_name: str,
        current_step_type: str,
        plan_steps_summary: list[str],
    ) -> None:
        deadline = time.monotonic() + seconds
        while True:
            if self._plan_stop.is_set():
                return
            self._honor_hold_point(
                current_step_index=current_step_index,
                total_steps=total_steps,
                current_step_name=current_step_name,
                current_step_type=current_step_type,
                current_step_status="hold_requested",
                plan_steps_summary=plan_steps_summary,
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.1, remaining))

    def _honor_hold_point(
        self,
        *,
        current_step_index: int | None,
        total_steps: int | None,
        current_step_name: str | None,
        current_step_type: str | None,
        current_step_status: str | None,
        plan_steps_summary: list[str],
    ) -> None:
        if self._plan_stop.is_set() or not self._plan_hold_requested.is_set():
            return

        with self._lock:
            self._is_held = True
            self._current_step_index = current_step_index
            self._total_steps = total_steps
            self._current_step_name = current_step_name
            self._current_step_type = current_step_type
            self._current_step_status = "held"

        self._emit_progress(
            current_step_index=current_step_index,
            total_steps=total_steps,
            current_step_name=current_step_name,
            current_step_type=current_step_type,
            current_step_status="held",
            plan_steps_summary=plan_steps_summary,
            is_held=True,
            hold_requested=True,
        )

        while True:
            if self._plan_stop.is_set():
                return
            if not self._plan_hold_requested.is_set():
                break
            if self._plan_resume.wait(timeout=0.1):
                self._plan_resume.clear()
                if not self._plan_hold_requested.is_set():
                    break

        with self._lock:
            self._is_held = False
            self._current_step_status = current_step_status

        self._emit_progress(
            current_step_index=current_step_index,
            total_steps=total_steps,
            current_step_name=current_step_name,
            current_step_type=current_step_type,
            current_step_status=current_step_status,
            plan_steps_summary=plan_steps_summary,
            is_held=False,
            hold_requested=False,
        )

    def _lookup_state_path(self, snapshot: Mapping[str, Any], path: str) -> Any:
        current: Any = snapshot
        for part in path.split('.'):
            if isinstance(current, Mapping) and part in current:
                current = current[part]
                continue
            raise KeyError(f"State path not found: {path}")
        return current

    def _summarize_step(self, index: int, step: Mapping[str, Any]) -> str:
        step_type = self._require_step_type(step)
        name = self._get_optional_step_string(step, "name")
        if name:
            return f"{index}:{step_type}:{name}"
        return f"{index}:{step_type}"

    def _script_progress_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "script_id": self._script_id,
                "name": self._script_name,
                "pid": self._process.pid if self._process is not None else os.getpid(),
                "launch_mode": self._launch_mode,
                "command": list(self._command),
                "cwd": self._cwd,
                "current_step_index": self._current_step_index,
                "total_steps": self._total_steps,
                "current_step_name": self._current_step_name,
                "current_step_type": self._current_step_type,
                "current_step_status": self._current_step_status,
                "plan_steps_summary": list(self._plan_steps_summary),
                "captured_output_lines": list(self._captured_output_lines),
                "is_held": self._is_held,
                "hold_requested": self._plan_hold_requested.is_set(),
                "supports_hold_continue": bool(self._launch_mode == "plan"),
            }

    def _build_plan_control_result(self, *, status: str) -> dict[str, Any]:
        snapshot = self._script_progress_snapshot()
        snapshot["status"] = status
        return snapshot

    def _utc_now_iso(self) -> str:
        return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()) + f".{int((time.time() % 1)*1000):03d}Z"
