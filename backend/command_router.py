# backend/command_router.py

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from uuid import uuid4

from historymanager.manager import isoformat_z

from .bus_manager import BusManager
from .device_registry import DeviceRegistry


@dataclass
class CommandDispatchResult:
    success: bool
    status: str
    command_name: str
    device_id: str | None
    dispatched_via: str
    adapter_name: str
    request_id: str | None = None
    request_source: str | None = None
    authority_level: str | None = None
    requested_at: str | None = None
    run_mode: str | None = None
    result_summary: Any = None
    command_event: dict[str, Any] | None = None
    rejection_reason: str | None = None
    interlock_reason: str | None = None
    error: str | None = None
    validation_errors: list[str] = field(default_factory=list)
    state_reasons: list[str] = field(default_factory=list)


class CommandRouter:
    """Backend-owned command router with explicit run-mode and state-aware guards."""

    _GLOBAL_ABORT_NAMES = {"abort", "emergency_stop", "estop"}
    _GLOBAL_ABORT_METHODS = ("abort", "emergency_stop", "estop", "stop")
    _VALVE_OPEN_NAMES = {"open", "open_valve", "valve_open"}
    _VALVE_CLOSE_NAMES = {"close", "close_valve", "valve_close"}
    _VALVE_OPEN_METHODS = ("open", "open_valve", "openValve", "set_open", "setOpen")
    _VALVE_CLOSE_METHODS = ("close", "close_valve", "closeValve", "set_close", "setClose")
    _ALWAYS_ALLOWED_WITHOUT_BUS = _GLOBAL_ABORT_NAMES | {"noop", "dry_run"}
    _KNOWN_AUTHORITY_LEVELS = {"observer", "operator", "supervisor", "engineer", "script", "system"}

    def __init__(
        self,
        *,
        device_registry: DeviceRegistry,
        bus_manager: BusManager,
        state_snapshot_getter: Callable[[], Mapping[str, Any]] | None = None,
    ) -> None:
        self.device_registry = device_registry
        self.bus_manager = bus_manager
        self.state_snapshot_getter = state_snapshot_getter

    def route_command(self, payload: Mapping[str, Any]) -> CommandDispatchResult:
        command_name = self._require_non_empty_string(payload, "command_name")
        device_id = self._get_optional_string(payload, "device_id")
        command_args = self._normalize_args(payload.get("command_args"))
        command_kwargs = self._normalize_kwargs(payload.get("command_kwargs"))
        mock_only = bool(payload.get("mock_only", False))
        dry_run = bool(payload.get("dry_run", False)) or command_name in {"noop", "dry_run"}
        request_id = self._get_optional_string(payload, "request_id") or uuid4().hex
        request_source = self._get_optional_string(payload, "request_source") or "gui"
        authority_level = self._get_optional_string(payload, "authority_level") or (
            "script" if request_source == "script" else "operator"
        )
        requested_at = self._get_optional_string(payload, "requested_at") or isoformat_z()
        allow_when_script_held = bool(payload.get("allow_when_script_held", False))
        stale_after_seconds = self._get_optional_float(payload, "stale_after_seconds")
        if stale_after_seconds is None:
            stale_after_seconds = 15.0

        validation_errors: list[str] = []
        state_reasons: list[str] = []
        snapshot = self._get_state_snapshot()
        run_mode = self._extract_mode(snapshot)

        if authority_level not in self._KNOWN_AUTHORITY_LEVELS:
            validation_errors.append(
                f"Unsupported authority_level {authority_level!r}; allowed values are {sorted(self._KNOWN_AUTHORITY_LEVELS)}"
            )
            return self._reject(
                command_name=command_name,
                device_id=device_id,
                adapter_name="authority_guard",
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
                rejection_reason="unsupported_authority_level",
                validation_errors=validation_errors,
            )

        if run_mode == "playback" and not (mock_only or dry_run):
            state_reasons.append("backend run mode is playback")
            return self._reject(
                command_name=command_name,
                device_id=device_id,
                adapter_name="mode_guard",
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
                rejection_reason="commands_disabled_in_playback",
                interlock_reason="commands are disabled while playback mode is active",
                state_reasons=state_reasons,
            )

        run_state = snapshot.get("run", {}) if isinstance(snapshot.get("run"), Mapping) else {}
        run_status = str(run_state.get("status") or "").strip().lower()
        if run_status in {"finishing", "completed"} and command_name not in self._GLOBAL_ABORT_NAMES and not (mock_only or dry_run):
            state_reasons.append(f"run status is {run_status}")
            return self._reject(
                command_name=command_name,
                device_id=device_id,
                adapter_name="run_status_guard",
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
                rejection_reason="run_not_accepting_commands",
                interlock_reason="new commands are blocked while the run is finishing or completed",
                state_reasons=state_reasons,
            )

        if device_id is not None and device_id not in self.device_registry:
            validation_errors.append(f"Unknown device_id {device_id!r}")
            return self._reject(
                command_name=command_name,
                device_id=device_id,
                adapter_name="device_lookup",
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
                rejection_reason="unknown_device",
                validation_errors=validation_errors,
            )

        meta: dict[str, Any] | None = None
        runtime: Any = None
        if device_id is not None and device_id in self.device_registry:
            meta = self.device_registry.get_meta(device_id)
            runtime = self.device_registry.get_runtime(device_id)

            if not bool(meta.get("isControllable", False)):
                validation_errors.append(f"Device {device_id!r} is not controllable")
                return self._reject(
                    command_name=command_name,
                    device_id=device_id,
                    adapter_name="device_capability_guard",
                    request_id=request_id,
                    request_source=request_source,
                    authority_level=authority_level,
                    requested_at=requested_at,
                    run_mode=run_mode,
                    rejection_reason="device_not_controllable",
                    validation_errors=validation_errors,
                )

        interlock = self._check_interlocks(
            command_name=command_name,
            device_id=device_id,
            mock_only=mock_only,
            dry_run=dry_run,
            meta=meta,
            runtime=runtime,
            snapshot=snapshot,
            request_source=request_source,
            allow_when_script_held=allow_when_script_held,
            stale_after_seconds=stale_after_seconds,
        )
        if interlock is not None:
            state_reasons.extend(interlock[1])
            return self._reject(
                command_name=command_name,
                device_id=device_id,
                adapter_name=interlock[0],
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
                rejection_reason=interlock[2],
                interlock_reason=interlock[3],
                state_reasons=state_reasons,
            )

        if dry_run or mock_only:
            result_summary = {
                "status": "accepted_as_mock",
                "mock_only": mock_only,
                "dry_run": dry_run,
            }
            return self._accept(
                command_name=command_name,
                device_id=device_id,
                dispatched_via="mock",
                adapter_name="dry_run_adapter",
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
                result_summary=result_summary,
                command_event=self._build_command_event(
                    request_id=request_id,
                    request_source=request_source,
                    authority_level=authority_level,
                    requested_at=requested_at,
                    run_mode=run_mode,
                    command_name=command_name,
                    device_id=device_id,
                    dispatched_via="mock",
                    adapter_name="dry_run_adapter",
                    command_args=command_args,
                    command_kwargs=command_kwargs,
                    mock_only=mock_only,
                    dry_run=dry_run,
                ),
            )

        if command_name in self._GLOBAL_ABORT_NAMES and device_id is None:
            return self._dispatch_global_abort(
                command_name=command_name,
                command_args=command_args,
                command_kwargs=command_kwargs,
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
            )

        if meta is not None and runtime is not None:
            device_type = str(meta.get("deviceType") or "")
            if self._looks_like_valve(device_type):
                valve_result = self._dispatch_valve_command(
                    command_name=command_name,
                    device_id=device_id,
                    runtime=runtime,
                    command_args=command_args,
                    command_kwargs=command_kwargs,
                    request_id=request_id,
                    request_source=request_source,
                    authority_level=authority_level,
                    requested_at=requested_at,
                    run_mode=run_mode,
                )
                if valve_result is not None:
                    return valve_result

            return self._dispatch_runtime_method(
                command_name=command_name,
                device_id=device_id,
                runtime=runtime,
                command_args=command_args,
                command_kwargs=command_kwargs,
                adapter_name="runtime_method_adapter",
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
            )

        return self._reject(
            command_name=command_name,
            device_id=device_id,
            adapter_name="command_scope_guard",
            request_id=request_id,
            request_source=request_source,
            authority_level=authority_level,
            requested_at=requested_at,
            run_mode=run_mode,
            rejection_reason="device_id_required",
            interlock_reason="non-global commands require a target device_id",
        )

    def _dispatch_global_abort(
        self,
        *,
        command_name: str,
        command_args: list[Any],
        command_kwargs: dict[str, Any],
        request_id: str,
        request_source: str,
        authority_level: str,
        requested_at: str,
        run_mode: str | None,
    ) -> CommandDispatchResult:
        invoked: list[dict[str, str]] = []
        for device in self.device_registry.get_gui_device_presentations():
            device_id = device.get("id")
            if not isinstance(device_id, str):
                continue
            if not bool(device.get("isControllable", False)):
                continue
            runtime = self.device_registry.get_runtime(device_id)
            method = self._resolve_first_callable(runtime, self._GLOBAL_ABORT_METHODS)
            if method is None:
                continue
            method_name = getattr(method, "__name__", None) or ""
            try:
                method(*command_args, **command_kwargs)
            except TypeError:
                method()
            invoked.append({"device_id": device_id, "method": method_name})

        if not invoked:
            return self._reject(
                command_name=command_name,
                device_id=None,
                adapter_name="global_abort_adapter",
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
                rejection_reason="no_global_abort_adapter",
                interlock_reason="no controllable runtime implements an abort-like method",
            )

        return self._accept(
            command_name=command_name,
            device_id=None,
            dispatched_via="runtime_global_abort",
            adapter_name="global_abort_adapter",
            request_id=request_id,
            request_source=request_source,
            authority_level=authority_level,
            requested_at=requested_at,
            run_mode=run_mode,
            result_summary={
                "status": "accepted",
                "invoked_count": len(invoked),
                "invoked_devices": invoked,
            },
            command_event=self._build_command_event(
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
                command_name=command_name,
                device_id=None,
                dispatched_via="runtime_global_abort",
                adapter_name="global_abort_adapter",
                command_args=command_args,
                command_kwargs=command_kwargs,
                mock_only=False,
                dry_run=False,
            ),
        )

    def _dispatch_valve_command(
        self,
        *,
        command_name: str,
        device_id: str,
        runtime: Any,
        command_args: list[Any],
        command_kwargs: dict[str, Any],
        request_id: str,
        request_source: str,
        authority_level: str,
        requested_at: str,
        run_mode: str | None,
    ) -> CommandDispatchResult | None:
        if command_name in self._VALVE_OPEN_NAMES:
            return self._dispatch_runtime_method_candidates(
                command_name=command_name,
                device_id=device_id,
                runtime=runtime,
                method_names=self._VALVE_OPEN_METHODS,
                command_args=command_args,
                command_kwargs=command_kwargs,
                adapter_name="valve_adapter",
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
            )
        if command_name in self._VALVE_CLOSE_NAMES:
            return self._dispatch_runtime_method_candidates(
                command_name=command_name,
                device_id=device_id,
                runtime=runtime,
                method_names=self._VALVE_CLOSE_METHODS,
                command_args=command_args,
                command_kwargs=command_kwargs,
                adapter_name="valve_adapter",
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
            )
        return None

    def _dispatch_runtime_method_candidates(
        self,
        *,
        command_name: str,
        device_id: str,
        runtime: Any,
        method_names: tuple[str, ...],
        command_args: list[Any],
        command_kwargs: dict[str, Any],
        adapter_name: str,
        request_id: str,
        request_source: str,
        authority_level: str,
        requested_at: str,
        run_mode: str | None,
    ) -> CommandDispatchResult:
        method = self._resolve_first_callable(runtime, method_names)
        if method is None:
            return self._reject(
                command_name=command_name,
                device_id=device_id,
                adapter_name=adapter_name,
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
                rejection_reason="no_matching_runtime_method",
                interlock_reason=f"runtime has none of the expected methods: {', '.join(method_names)}",
            )

        method_name = getattr(method, "__name__", None) or method_names[0]
        try:
            result = method(*command_args, **command_kwargs)
        except Exception as exc:
            return self._failed(
                command_name=command_name,
                device_id=device_id,
                dispatched_via="runtime_method",
                adapter_name=adapter_name,
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
                error=str(exc),
            )

        return self._accept(
            command_name=command_name,
            device_id=device_id,
            dispatched_via="runtime_method",
            adapter_name=adapter_name,
            request_id=request_id,
            request_source=request_source,
            authority_level=authority_level,
            requested_at=requested_at,
            run_mode=run_mode,
            result_summary={
                "status": "accepted",
                "method_name": method_name,
                "return_value": result,
            },
            command_event=self._build_command_event(
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
                command_name=command_name,
                device_id=device_id,
                dispatched_via="runtime_method",
                adapter_name=adapter_name,
                command_args=command_args,
                command_kwargs=command_kwargs,
                mock_only=False,
                dry_run=False,
            ),
        )

    def _dispatch_runtime_method(
        self,
        *,
        command_name: str,
        device_id: str,
        runtime: Any,
        command_args: list[Any],
        command_kwargs: dict[str, Any],
        adapter_name: str,
        request_id: str,
        request_source: str,
        authority_level: str,
        requested_at: str,
        run_mode: str | None,
    ) -> CommandDispatchResult:
        method = getattr(runtime, command_name, None)
        if not callable(method):
            return self._reject(
                command_name=command_name,
                device_id=device_id,
                adapter_name=adapter_name,
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
                rejection_reason="no_matching_runtime_method",
                interlock_reason=f"runtime does not implement method {command_name!r}",
            )
        try:
            result = method(*command_args, **command_kwargs)
        except Exception as exc:
            return self._failed(
                command_name=command_name,
                device_id=device_id,
                dispatched_via="runtime_method",
                adapter_name=adapter_name,
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
                error=str(exc),
            )
        return self._accept(
            command_name=command_name,
            device_id=device_id,
            dispatched_via="runtime_method",
            adapter_name=adapter_name,
            request_id=request_id,
            request_source=request_source,
            authority_level=authority_level,
            requested_at=requested_at,
            run_mode=run_mode,
            result_summary={
                "status": "accepted",
                "method_name": command_name,
                "return_value": result,
            },
            command_event=self._build_command_event(
                request_id=request_id,
                request_source=request_source,
                authority_level=authority_level,
                requested_at=requested_at,
                run_mode=run_mode,
                command_name=command_name,
                device_id=device_id,
                dispatched_via="runtime_method",
                adapter_name=adapter_name,
                command_args=command_args,
                command_kwargs=command_kwargs,
                mock_only=False,
                dry_run=False,
            ),
        )

    def _check_interlocks(
        self,
        *,
        command_name: str,
        device_id: str | None,
        mock_only: bool,
        dry_run: bool,
        meta: Mapping[str, Any] | None,
        runtime: Any,
        snapshot: Mapping[str, Any],
        request_source: str,
        allow_when_script_held: bool,
        stale_after_seconds: float,
    ) -> tuple[str, list[str], str, str] | None:
        if mock_only or dry_run or command_name in self._ALWAYS_ALLOWED_WITHOUT_BUS:
            return None

        state_reasons: list[str] = []

        bus_state = snapshot.get("bus", {}) if isinstance(snapshot, Mapping) else {}
        if isinstance(bus_state, Mapping):
            if bool(bus_state.get("reconnecting", False)):
                state_reasons.append("bus is reconnecting")
                return (
                    "bus_guard",
                    state_reasons,
                    "bus_reconnecting",
                    "commands are blocked while the backend bus is reconnecting",
                )
            if not bool(bus_state.get("connected", False)):
                state_reasons.append("bus is not connected")
                return (
                    "bus_guard",
                    state_reasons,
                    "bus_not_connected",
                    "commands are blocked while the backend bus is disconnected",
                )

        script_state = snapshot.get("script_runner", {}) if isinstance(snapshot, Mapping) else {}
        if request_source == "script" and isinstance(script_state, Mapping):
            if bool(script_state.get("is_held", False)) and not allow_when_script_held:
                state_reasons.append("script runner is held")
                return (
                    "script_hold_guard",
                    state_reasons,
                    "script_is_held",
                    "script-issued commands are blocked while the script runner is held",
                )

        device_runtime = snapshot.get("device_runtime", {}) if isinstance(snapshot, Mapping) else {}
        runtime_by_id = device_runtime.get("by_id", {}) if isinstance(device_runtime, Mapping) else {}
        device_state = runtime_by_id.get(device_id, {}) if isinstance(runtime_by_id, Mapping) and device_id is not None else {}
        if isinstance(device_state, Mapping):
            if bool(device_state.get("command_inhibit", False)):
                state_reasons.append("device reports command_inhibit=true")
                return (
                    "device_state_guard",
                    state_reasons,
                    "device_command_inhibited",
                    "device state currently inhibits outbound commands",
                )
            if bool(device_state.get("command_busy", False)) or bool(device_state.get("busy", False)):
                state_reasons.append("device reports busy=true")
                return (
                    "device_state_guard",
                    state_reasons,
                    "device_busy",
                    "device is busy and cannot accept another command yet",
                )
            if bool(device_state.get("faulted", False)) or bool(device_state.get("is_faulted", False)):
                state_reasons.append("device reports faulted=true")
                return (
                    "device_state_guard",
                    state_reasons,
                    "device_faulted",
                    "device is faulted and command dispatch is blocked",
                )
            age_value = device_state.get("telemetry_age_seconds")
            if isinstance(age_value, (int, float)) and float(age_value) > stale_after_seconds:
                state_reasons.append(
                    f"device telemetry is stale at {float(age_value):.3f}s (> {stale_after_seconds:.3f}s)"
                )
                return (
                    "device_state_guard",
                    state_reasons,
                    "device_telemetry_stale",
                    "device telemetry is too old for a safe command dispatch",
                )

        if meta is not None and runtime is not None:
            if not bool(getattr(runtime, "live_registered", False)):
                state_reasons.append(f"device {device_id!r} is not live registered")
                return (
                    "device_registration_guard",
                    state_reasons,
                    "device_not_live_registered",
                    f"device {device_id!r} is not live registered",
                )

        return None

    def _build_command_event(
        self,
        *,
        request_id: str,
        request_source: str,
        authority_level: str,
        requested_at: str,
        run_mode: str | None,
        command_name: str,
        device_id: str | None,
        dispatched_via: str,
        adapter_name: str,
        command_args: list[Any],
        command_kwargs: dict[str, Any],
        mock_only: bool,
        dry_run: bool,
    ) -> dict[str, Any]:
        return {
            "event_kind": "command_dispatch",
            "requested_at": requested_at,
            "request_id": request_id,
            "request_source": request_source,
            "authority_level": authority_level,
            "run_mode": run_mode,
            "command_name": command_name,
            "device_id": device_id,
            "command_args": list(command_args),
            "command_kwargs": dict(command_kwargs),
            "dispatched_via": dispatched_via,
            "adapter_name": adapter_name,
            "mock_only": bool(mock_only),
            "dry_run": bool(dry_run),
        }

    def _accept(
        self,
        *,
        command_name: str,
        device_id: str | None,
        dispatched_via: str,
        adapter_name: str,
        request_id: str | None,
        request_source: str | None,
        authority_level: str | None,
        requested_at: str | None,
        run_mode: str | None,
        result_summary: Any,
        command_event: dict[str, Any] | None,
    ) -> CommandDispatchResult:
        return CommandDispatchResult(
            success=True,
            status="accepted",
            command_name=command_name,
            device_id=device_id,
            dispatched_via=dispatched_via,
            adapter_name=adapter_name,
            request_id=request_id,
            request_source=request_source,
            authority_level=authority_level,
            requested_at=requested_at,
            run_mode=run_mode,
            result_summary=result_summary,
            command_event=command_event,
        )

    def _reject(
        self,
        *,
        command_name: str,
        device_id: str | None,
        adapter_name: str,
        request_id: str | None,
        request_source: str | None,
        authority_level: str | None,
        requested_at: str | None,
        run_mode: str | None,
        rejection_reason: str,
        interlock_reason: str | None = None,
        validation_errors: list[str] | None = None,
        state_reasons: list[str] | None = None,
    ) -> CommandDispatchResult:
        return CommandDispatchResult(
            success=False,
            status="rejected",
            command_name=command_name,
            device_id=device_id,
            dispatched_via="none",
            adapter_name=adapter_name,
            request_id=request_id,
            request_source=request_source,
            authority_level=authority_level,
            requested_at=requested_at,
            run_mode=run_mode,
            result_summary=None,
            command_event=None,
            rejection_reason=rejection_reason,
            interlock_reason=interlock_reason,
            validation_errors=list(validation_errors or []),
            state_reasons=list(state_reasons or []),
        )

    def _failed(
        self,
        *,
        command_name: str,
        device_id: str | None,
        dispatched_via: str,
        adapter_name: str,
        request_id: str | None,
        request_source: str | None,
        authority_level: str | None,
        requested_at: str | None,
        run_mode: str | None,
        error: str,
    ) -> CommandDispatchResult:
        return CommandDispatchResult(
            success=False,
            status="failed",
            command_name=command_name,
            device_id=device_id,
            dispatched_via=dispatched_via,
            adapter_name=adapter_name,
            request_id=request_id,
            request_source=request_source,
            authority_level=authority_level,
            requested_at=requested_at,
            run_mode=run_mode,
            result_summary=None,
            command_event=None,
            error=error,
        )

    def _get_state_snapshot(self) -> Mapping[str, Any]:
        if self.state_snapshot_getter is None:
            return {}
        snapshot = self.state_snapshot_getter()
        if isinstance(snapshot, Mapping):
            return snapshot
        return {}

    def _extract_mode(self, snapshot: Mapping[str, Any]) -> str | None:
        run_state = snapshot.get("run")
        if isinstance(run_state, Mapping):
            mode = run_state.get("mode")
            if isinstance(mode, str) and mode.strip():
                return mode.strip()
        return None

    def _looks_like_valve(self, device_type: str) -> bool:
        lowered = device_type.strip().lower()
        return "valve" in lowered or "solenoid" in lowered

    def _resolve_first_callable(self, runtime: Any, method_names: tuple[str, ...]) -> Callable[..., Any] | None:
        for method_name in method_names:
            method = getattr(runtime, method_name, None)
            if callable(method):
                return method
        return None

    def _require_non_empty_string(self, payload: Mapping[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Command payload field {key!r} must be a non-empty string")
        return value.strip()

    def _get_optional_string(self, payload: Mapping[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None

    def _get_optional_float(self, payload: Mapping[str, Any], key: str) -> float | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, (int, float)):
            raise ValueError(f"Command payload field {key!r} must be a number when provided")
        return float(value)

    def _normalize_args(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Command payload field 'command_args' must be a list when provided")
        return list(value)

    def _normalize_kwargs(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("Command payload field 'command_kwargs' must be an object when provided")
        return dict(value)
