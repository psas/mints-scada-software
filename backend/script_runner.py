"""backend/script_runner.py

Backend-owned script execution and plan-mode control.

This module runs backend-owned scripts in one of three launch modes:

- direct subprocess execution for explicit command payloads
- legacy inline Python execution through ``script_host.py`` and ``ScriptHostProxy``
- backend-native plan execution on a worker thread

It also exposes plan-mode hold/continue behavior, relays script-host messages
back into backend callbacks, and reports script progress through snapshot-style
payloads.
"""

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
    """Describe a successfully started backend-owned script.

    Attributes:
        script_id: Backend-generated identifier for the running script session.
        name: User-facing script name.
        pid: Process identifier for subprocess and legacy-host modes, or the
            current backend PID for plan mode.
        launch_mode: Launch mode used for this run.
        command: Effective command summary associated with the launch.
        cwd: Working directory used for the script, if any.
        current_step_index: Current plan step index when the script starts in
            plan mode.
        total_steps: Total number of normalized plan steps for plan mode.
        current_step_name: Current step name for plan mode startup snapshots.
        current_step_type: Current step type for plan mode startup snapshots.
        current_step_status: Current step status for plan mode startup snapshots.
        plan_steps_summary: Human-readable summary strings for normalized plan
            steps.
    """

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
    """Own backend-side script lifecycle, progress, and control.

    The runner supports a single active script at a time. Legacy and explicit
    command payloads run as subprocess-backed executions, while backend-native
    plan payloads run on a worker thread with cooperative hold and continue
    checkpoints.

    Start payloads currently support:

    - ``{"name": "...", "command": [...], "cwd": "...", "env": {...}}``
    - ``{"name": "...", "inline_python": "...", "cwd": "...", "env": {...}}``
    - ``{"name": "...", "plan_steps": [...]}``
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
        """Initialize the runner and its callback dependencies.

        Args:
            command_dispatcher: Backend callback used to dispatch canonical
                command-request payloads from plan steps and legacy script-host
                messages.
            state_snapshot_getter: Backend callback that returns the current
                authoritative state snapshot for wait-state steps and legacy
                device-id discovery.
            progress_callback: Callback invoked with progress snapshots when the
                active script advances or changes hold state.
            abort_dispatcher: Optional dedicated callback for abort requests
                emitted by the script host. Falls back to ``command_dispatcher``
                when omitted.
            output_callback: Callback invoked when the legacy script host emits
                captured output lines.
            project_root: Repository root used to resolve runtime helper paths
                such as ``script_host.py``. Defaults to the current working
                directory when omitted.
        """
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
        self._project_root = (
            Path(project_root).expanduser().resolve()
            if project_root
            else Path.cwd().resolve()
        )
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
        """Return whether a subprocess or plan thread is still active.

        Returns:
            True when the subprocess-backed launch is alive or the current
            plan-mode worker thread is alive.
        """
        with self._lock:
            process_running = self._process is not None and self._process.poll() is None
            plan_running = (
                self._plan_thread is not None and self._plan_thread.is_alive()
            )
            return process_running or plan_running

    def get_status_snapshot(self) -> dict[str, Any]:
        """Return the current script progress snapshot with runtime flags.

        Returns:
            A snapshot dictionary describing the active script, including
            whether a script is currently running and whether the launch mode
            supports hold and continue.
        """
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
        """Start a backend-owned script from a supported payload shape.

        The payload is routed to plan mode, legacy inline-host mode, or direct
        subprocess mode based on the fields it defines.

        Args:
            payload: Script start payload. Supported shapes include
                ``command``, ``inline_python``, and ``plan_steps`` payloads.
            script_id: Backend-generated script identifier for this launch.
            on_exit: Callback invoked after the active script exits.

        Returns:
            Metadata describing the started script session.

        Raises:
            RuntimeError: If another backend-owned script is already running.
            ValueError: If required payload fields are missing or invalid.
        """
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

    def stop_script(
        self, *, reason: str = "operator_stop", timeout_s: float = 3.0
    ) -> dict[str, Any]:
        """Stop the active script and return a stop-result snapshot.

        Plan mode is stopped cooperatively by setting the stop flag and waking
        any held step. Subprocess-backed modes are terminated by process group
        and escalated to ``SIGKILL`` when they do not exit within the timeout.

        Args:
            reason: Backend-visible reason string for the stop request.
            timeout_s: Grace period before subprocess shutdown escalates from
                ``SIGTERM`` to ``SIGKILL``.

        Returns:
            A result dictionary describing how the active script stopped.

        Raises:
            RuntimeError: If no backend-owned script is currently running.
        """
        log.info("stop_script requested: reason=%r, timeout_s=%s", reason, timeout_s)
        with self._lock:
            launch_mode = self._launch_mode
            if launch_mode == "plan":
                if self._plan_thread is None or not self._plan_thread.is_alive():
                    raise RuntimeError("No running backend-owned script to stop")

                script_id = self._script_id
                script_name = self._script_name
                pid = os.getpid()
                log.info(
                    "Stopping plan-mode script %r (id=%s, reason=%r)",
                    script_name,
                    script_id,
                    reason,
                )
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
                log.info(
                    "Stopping subprocess script %r (id=%s, pid=%s, reason=%r)",
                    script_name,
                    script_id,
                    pid,
                    reason,
                )

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
            log.warning(
                "Script pid=%s did not exit after SIGTERM (%.1fs); escalating to SIGKILL",
                process.pid,
                timeout_s,
            )
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return_code = process.wait(timeout=1.0)
            stopped_via = "sigkill"

        log.info(
            "Script stopped: pid=%s, stopped_via=%s, returncode=%s, reason=%r",
            process.pid,
            stopped_via,
            return_code,
            reason,
        )
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
        """Request a cooperative hold for the active plan-mode script.

        Args:
            reason: Unused operator-visible reason string kept for API
                symmetry with other control methods.

        Returns:
            A control-result snapshot describing whether the script is already
            held or has a hold pending.

        Raises:
            RuntimeError: If no script is running or the active script is not
                using plan mode.
        """
        del reason
        with self._lock:
            if not self.is_running:
                raise RuntimeError("No running backend-owned script to hold")
            if self._launch_mode != "plan":
                raise RuntimeError(
                    "Hold is only supported for backend plan-mode scripts"
                )

            self._plan_hold_requested.set()
            self._plan_resume.clear()

            if self._is_held:
                status = "held"
            else:
                status = "hold_requested"

            return self._build_plan_control_result(status=status)

    def continue_script(self, *, reason: str = "operator_continue") -> dict[str, Any]:
        """Resume a held plan-mode script.

        Args:
            reason: Unused operator-visible reason string kept for API
                symmetry with other control methods.

        Returns:
            A control-result snapshot describing the resumed plan state.

        Raises:
            RuntimeError: If no script is running, the active script is not in
                plan mode, or the plan is not currently held.
        """
        del reason
        with self._lock:
            if not self.is_running:
                raise RuntimeError("No running backend-owned script to continue")
            if self._launch_mode != "plan":
                raise RuntimeError(
                    "Continue is only supported for backend plan-mode scripts"
                )
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
        """Stop the active script during backend shutdown.

        Returns:
            None.
        """
        with self._lock:
            running = self.is_running
        if running:
            log.info(
                "ScriptRunner.shutdown(): stopping running script (reason=backend_shutdown)"
            )
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
        """Start legacy inline Python through the backend script host process.

        This mode launches ``script_host.py`` through ``ScriptHostProxy``,
        sends the inline script text for execution, and watches structured host
        messages for output, command requests, abort requests, and exit.

        Args:
            payload: Script start payload containing ``inline_python`` and
                optional script-host metadata.
            script_id: Backend-generated script identifier for this launch.
            name: User-facing script name.
            cwd: Working directory to run the host under.
            on_exit: Callback invoked after the host reports script exit.

        Returns:
            Metadata describing the started legacy-host session.

        Raises:
            ValueError: If ``inline_python`` is missing or empty.
            RuntimeError: If the script host does not remain available after
                execution starts.
        """
        script_text = payload.get("inline_python")
        if not isinstance(script_text, str) or not script_text.strip():
            raise ValueError("'inline_python' must be a non-empty string")

        resolved_cwd = cwd or str(self._project_root)
        host_proxy = ScriptHostProxy(project_root=self._project_root)
        host_ready = host_proxy.start(
            script_path=payload.get("script_path"), cwd=resolved_cwd
        )
        host_pid = host_ready.get("payload", {}).get("pid")

        execute_started = host_proxy.execute_legacy_script(
            script_text=script_text,
            device_ids=self._build_legacy_device_ids(),
            timeout_s=3.0,
        )

        process = host_proxy.process
        if process is None:
            raise RuntimeError(
                "Legacy script host did not stay running after execute_started"
            )

        self._process = process
        self._host_proxy = host_proxy
        self._plan_thread = None
        self._script_id = script_id
        self._script_name = name
        self._launch_mode = "inline_python"
        self._command = [
            (
                self.python_executable
                if hasattr(self, "python_executable")
                else sys.executable
            ),
            "-u",
            str(self._project_root / "scripts" / "script_runtime" / "script_host.py"),
        ]
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
        """Start a detached subprocess-backed script execution.

        Args:
            payload: Script start payload containing a validated ``command`` or
                inline-Python launch request.
            script_id: Backend-generated script identifier for this launch.
            name: User-facing script name.
            cwd: Working directory for the child process.
            on_exit: Callback invoked after the subprocess exits.

        Returns:
            Metadata describing the started subprocess-backed session.

        Raises:
            ValueError: If the payload cannot be converted into an executable
                command.
        """
        env_overrides = self._get_optional_string_mapping(payload, "env") or {}
        command = self._build_command(payload)
        if not command:
            raise ValueError(
                "Script start payload must define either 'command', 'inline_python', or 'plan_steps'"
            )

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
        """Start a backend-native plan-mode script on a worker thread.

        Args:
            payload: Script start payload containing ``plan_steps``.
            script_id: Backend-generated script identifier for this launch.
            name: User-facing script name.
            cwd: Working directory metadata associated with the plan.
            on_exit: Callback invoked after plan execution exits.

        Returns:
            Metadata describing the started plan-mode session, including the
            normalized step summary.

        Raises:
            ValueError: If ``plan_steps`` is missing, empty, or invalid.
        """
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
        self._plan_steps_summary = [
            self._summarize_step(i + 1, step) for i, step in enumerate(plan_steps)
        ]

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
        """Execute normalized plan steps sequentially on the worker thread.

        This method emits progress before and after each step, honors
        cooperative hold points, and reports exit information through the
        registered ``on_exit`` callback unless the watcher has already been
        stopped by an explicit backend shutdown path.

        Args:
            plan_steps: Normalized plan step dictionaries to execute.

        Returns:
            None.
        """
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
        """Execute one normalized plan step.

        Supported step types are ``sleep``, ``note``, ``command_request``,
        ``wait_state``, and ``fail``.

        Args:
            step_type: Normalized plan step type.
            step: Full plan step payload.
            current_step_index: One-based current step index.
            total_steps: Total plan step count.
            current_step_name: Resolved step name used in progress payloads.
            plan_steps_summary: Current summary strings for the full plan.

        Returns:
            None.

        Raises:
            RuntimeError: If a required dispatcher or state snapshot callback is
                missing, or if a command step reports failure.
            TimeoutError: If a wait-state step does not reach the expected
                value before its timeout.
            ValueError: If the step payload is invalid or uses an unsupported
                step type.
        """
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
                raise RuntimeError(
                    "Plan-mode command_request step requires a command dispatcher callback"
                )
            payload = step.get("payload")
            if not isinstance(payload, Mapping):
                raise ValueError(
                    "Plan-mode command_request step must include an object 'payload'"
                )
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
                raise RuntimeError(
                    "Plan-mode wait_state step requires a state snapshot callback"
                )
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
            raise TimeoutError(
                f"Plan wait_state step timed out waiting for {path!r} == {expected!r}"
            )

        if step_type == "fail":
            message = (
                self._get_optional_step_string(step, "message")
                or "Plan requested failure"
            )
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
        """Update internal progress state and publish a progress snapshot.

        Args:
            current_step_index: Current one-based plan step index, if any.
            total_steps: Total plan step count, if known.
            current_step_name: Resolved step name.
            current_step_type: Resolved step type.
            current_step_status: Current step status string.
            plan_steps_summary: Summary strings for all normalized plan steps.
            is_held: Explicit hold flag override. Defaults to the runner's
                current hold state when omitted.
            hold_requested: Explicit hold-request flag override. Defaults to the
                current hold-request event state when omitted.

        Returns:
            None.
        """
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
        """Read and handle messages from the legacy script host until exit.

        The host watcher consumes structured script-host messages, forwards
        output and command-related messages through backend callbacks, and
        emits a final exit payload to ``on_exit``.

        Returns:
            None.
        """
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
                if isinstance(payload.get("failure_message"), str) and payload.get(
                    "failure_message"
                ):
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
        """Capture one output message from the legacy script host.

        Args:
            payload: Script-host output payload. Expected fields include
                ``text``, ``level``, and ``wall_time``.

        Returns:
            None.
        """
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
                "output_level": (
                    payload.get("level")
                    if isinstance(payload.get("level"), str)
                    else "info"
                ),
                "progress_wall_time": (
                    payload.get("wall_time")
                    if isinstance(payload.get("wall_time"), str)
                    else self._utc_now_iso()
                ),
            }
        if callable(callback):
            callback(info)

    def _handle_host_command_request(self, payload: Mapping[str, Any]) -> None:
        """Dispatch a command request emitted by the legacy script host.

        Args:
            payload: Command-request payload emitted by the host.

        Returns:
            None.
        """
        if self._command_dispatcher is None:
            return
        try:
            self._command_dispatcher(dict(payload))
        except Exception:
            log.exception("Script host command request failed")

    def _handle_host_abort_request(self, payload: Mapping[str, Any]) -> None:
        """Dispatch an abort request emitted by the legacy script host.

        Args:
            payload: Abort-request payload emitted by the host.

        Returns:
            None.
        """
        dispatcher = self._abort_dispatcher or self._command_dispatcher
        if dispatcher is None:
            return
        try:
            dispatcher(dict(payload))
        except Exception:
            log.exception("Script host abort request failed")

    def _watch_process(self) -> None:
        """Wait for a subprocess-backed script to exit and report completion.

        Returns:
            None.
        """
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
        """Clear active-script runtime state after exit or forced stop.

        Returns:
            None.
        """
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
        """Build the executable command for a subprocess-backed launch.

        Explicit ``command`` payloads are passed through after validation.
        ``inline_python`` payloads resolve to the backend script-host command.

        Args:
            payload: Script start payload to inspect.

        Returns:
            The command list to execute, or an empty list when the payload does
            not define a subprocess-backed launch mode.

        Raises:
            ValueError: If the command payload is present but malformed.
        """
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
            return [
                sys.executable,
                "-u",
                str(
                    self._project_root / "scripts" / "script_runtime" / "script_host.py"
                ),
            ]

        return []

    def _build_legacy_device_ids(self) -> list[str]:
        """Extract currently registered device IDs for legacy script-host setup.

        Returns:
            Device IDs from ``state_snapshot_getter()['device_registry']['devices']``
            when that structure is available. Returns an empty list when the
            snapshot callback is missing, fails, or does not provide the
            expected shape.
        """
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
        """Validate and normalize a raw plan-step list.

        Args:
            value: Raw ``plan_steps`` value from a script start payload.

        Returns:
            A list of shallow-copied plan step dictionaries.

        Raises:
            ValueError: If the raw value is not a non-empty list of step
                objects with valid step types.
        """
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
        """Return a required non-empty string payload field.

        Args:
            payload: Payload mapping to inspect.
            key: Required string field name.

        Returns:
            The stripped string value.

        Raises:
            ValueError: If the field is missing, not a string, or empty.
        """
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Script payload must include a non-empty string '{key}'")
        return value.strip()

    def _get_optional_string(self, payload: Mapping[str, Any], key: str) -> str | None:
        """Return an optional stripped string payload field.

        Args:
            payload: Payload mapping to inspect.
            key: Optional string field name.

        Returns:
            The stripped string value, or None when the field is missing or
            blank.

        Raises:
            ValueError: If the field is present but not a string.
        """
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(
                f"Script payload field '{key}' must be a string when provided"
            )
        stripped = value.strip()
        return stripped or None

    def _get_optional_string_mapping(
        self,
        payload: Mapping[str, Any],
        key: str,
    ) -> dict[str, str] | None:
        """Return an optional mapping of string keys to string values.

        Args:
            payload: Payload mapping to inspect.
            key: Optional mapping field name.

        Returns:
            A copied dictionary of string keys and string values, or None when
            the field is missing.

        Raises:
            ValueError: If the field is present but not an object of strings.
        """
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError(
                f"Script payload field '{key}' must be an object when provided"
            )

        result: dict[str, str] = {}
        for env_key, env_value in value.items():
            if not isinstance(env_key, str):
                raise ValueError(f"Script env key {env_key!r} must be a string")
            if not isinstance(env_value, str):
                raise ValueError(f"Script env value for {env_key!r} must be a string")
            result[env_key] = env_value
        return result

    def _require_step_type(self, step: Mapping[str, Any]) -> str:
        """Return the required non-empty type for a plan step.

        Args:
            step: Plan step mapping to inspect.

        Returns:
            The stripped plan step type string.

        Raises:
            ValueError: If the step does not define a non-empty ``type``.
        """
        value = step.get("type")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Each plan step must include a non-empty string 'type'")
        return value.strip()

    def _get_step_name(self, step: Mapping[str, Any], index: int) -> str:
        """Return the display name for a plan step.

        Args:
            step: Plan step mapping.
            index: One-based step index.

        Returns:
            The explicit step name when present, otherwise a generated
            ``step_{index}_{type}`` fallback name.
        """
        name = step.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        return f"step_{index:02d}_{self._require_step_type(step)}"

    def _get_optional_step_string(
        self, step: Mapping[str, Any], key: str
    ) -> str | None:
        """Return an optional stripped string field from a plan step.

        Args:
            step: Plan step mapping to inspect.
            key: Optional string field name.

        Returns:
            The stripped string value, or None when the field is missing or
            blank.

        Raises:
            ValueError: If the field is present but not a string.
        """
        value = step.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"Plan step field '{key}' must be a string when provided")
        stripped = value.strip()
        return stripped or None

    def _require_non_empty_step_string(self, step: Mapping[str, Any], key: str) -> str:
        """Return a required non-empty string field from a plan step.

        Args:
            step: Plan step mapping to inspect.
            key: Required string field name.

        Returns:
            The stripped string value.

        Raises:
            ValueError: If the field is missing, not a string, or blank.
        """
        value = self._get_optional_step_string(step, key)
        if not value:
            raise ValueError(f"Plan step must include a non-empty string '{key}'")
        return value

    def _coerce_positive_number(self, value: Any, *, key: str) -> float:
        """Convert a numeric step field to a non-negative float.

        Args:
            value: Raw numeric value to convert.
            key: Field name used in validation errors.

        Returns:
            The converted float value.

        Raises:
            ValueError: If the value is not numeric or is negative.
        """
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
        """Sleep until the deadline while honoring stop and hold requests.

        Args:
            seconds: Sleep duration in seconds.
            current_step_index: One-based current plan step index.
            total_steps: Total plan step count.
            current_step_name: Resolved step name.
            current_step_type: Resolved step type.
            plan_steps_summary: Summary strings for the full plan.

        Returns:
            None.
        """
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
        """Pause at a cooperative hold point until continue or stop.

        Args:
            current_step_index: One-based current plan step index.
            total_steps: Total plan step count.
            current_step_name: Resolved step name.
            current_step_type: Resolved step type.
            current_step_status: Step status to restore after the hold releases.
            plan_steps_summary: Summary strings for the full plan.

        Returns:
            None.
        """
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
        """Resolve a dot-separated mapping path inside a state snapshot.

        Args:
            snapshot: State snapshot mapping to traverse.
            path: Dot-separated mapping path such as ``a.b.c``.

        Returns:
            The resolved value at the target path.

        Raises:
            KeyError: If any path segment is missing or a non-mapping value is
                encountered before the final segment.
        """
        current: Any = snapshot
        for part in path.split("."):
            if isinstance(current, Mapping) and part in current:
                current = current[part]
                continue
            raise KeyError(f"State path not found: {path}")
        return current

    def _summarize_step(self, index: int, step: Mapping[str, Any]) -> str:
        """Build the compact summary string stored for a plan step.

        Args:
            index: One-based step index.
            step: Plan step mapping.

        Returns:
            A summary string in ``index:type`` or ``index:type:name`` format.
        """
        step_type = self._require_step_type(step)
        name = self._get_optional_step_string(step, "name")
        if name:
            return f"{index}:{step_type}:{name}"
        return f"{index}:{step_type}"

    def _script_progress_snapshot(self) -> dict[str, Any]:
        """Return the current internal script progress snapshot.

        Returns:
            A snapshot dictionary describing the active script identity,
            execution mode, plan progress, captured host output, and hold state.
        """
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
        """Return the current plan snapshot plus a control-status field.

        Args:
            status: Control-result status such as ``held`` or ``continued``.

        Returns:
            The current script progress snapshot with ``status`` added.
        """
        snapshot = self._script_progress_snapshot()
        snapshot["status"] = status
        return snapshot

    def _utc_now_iso(self) -> str:
        """Return the current UTC timestamp in millisecond ISO-8601 form.

        Returns:
            A UTC timestamp string formatted as ``YYYY-MM-DDTHH:MM:SS.mmmZ``.
        """
        return (
            time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
            + f".{int((time.time() % 1)*1000):03d}Z"
        )
