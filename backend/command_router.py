from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from historymanager.manager import isoformat_z

from .bus_manager import BusManager
from .device_registry import DeviceRegistry


@dataclass
class CommandDispatchResult:
    success: bool
    command_name: str
    device_id: str | None
    dispatched_via: str
    result_summary: Any
    command_event: dict[str, Any]


class CommandRouter:
    """Backend-owned command routing skeleton.

    Current routing modes:
    - noop / dry_run
    - invoke a same-named callable on the backend runtime device

    This keeps the command path in backend now, while leaving room for
    device-specific adapters or packet-based routing in later commits.
    """

    def __init__(
        self,
        *,
        device_registry: DeviceRegistry,
        bus_manager: BusManager,
    ) -> None:
        self.device_registry = device_registry
        self.bus_manager = bus_manager

    def route_command(self, request: Mapping[str, Any]) -> CommandDispatchResult:
        command_name = self._require_non_empty_string(request, "command_name")
        device_id = self._get_optional_string(request, "device_id")
        command_args = self._get_optional_list(request, "command_args") or []
        command_kwargs = self._get_optional_mapping(request, "command_kwargs") or {}
        mock_only = self._get_optional_bool(request, "mock_only", default=False)

        request_wall_time = isoformat_z()

        if command_name in {"noop", "dry_run"} or mock_only:
            command_event = {
                "event_kind": "command_dispatch",
                "requested_at": request_wall_time,
                "command_name": command_name,
                "device_id": device_id,
                "command_args": list(command_args),
                "command_kwargs": dict(command_kwargs),
                "dispatched_via": "mock",
                "mock_only": True,
            }
            return CommandDispatchResult(
                success=True,
                command_name=command_name,
                device_id=device_id,
                dispatched_via="mock",
                result_summary={"status": "accepted_as_mock"},
                command_event=command_event,
            )

        if device_id is None:
            raise ValueError("command_request requires 'device_id' unless using noop/dry_run")

        if device_id not in self.device_registry:
            raise ValueError(f"Unknown device_id: {device_id}")

        runtime = self.device_registry.get_runtime(device_id)

        method = getattr(runtime, command_name, None)
        if not callable(method):
            raise ValueError(
                f"Runtime device {device_id!r} has no callable method {command_name!r}"
            )

        result = method(*command_args, **command_kwargs)

        command_event = {
            "event_kind": "command_dispatch",
            "requested_at": request_wall_time,
            "command_name": command_name,
            "device_id": device_id,
            "command_args": list(command_args),
            "command_kwargs": dict(command_kwargs),
            "dispatched_via": "runtime_method",
            "runtime_class": type(runtime).__name__,
        }

        return CommandDispatchResult(
            success=True,
            command_name=command_name,
            device_id=device_id,
            dispatched_via="runtime_method",
            result_summary=self._summarize_result(result),
            command_event=command_event,
        )

    def _require_non_empty_string(self, payload: Mapping[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Command payload must include a non-empty string '{key}'")
        return value.strip()

    def _get_optional_string(self, payload: Mapping[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"Command payload field '{key}' must be a string when provided")
        stripped = value.strip()
        return stripped or None

    def _get_optional_mapping(self, payload: Mapping[str, Any], key: str) -> dict[str, Any] | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError(f"Command payload field '{key}' must be an object when provided")
        return dict(value)

    def _get_optional_list(self, payload: Mapping[str, Any], key: str) -> list[Any] | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError(f"Command payload field '{key}' must be a list when provided")
        return list(value)

    def _get_optional_bool(
        self,
        payload: Mapping[str, Any],
        key: str,
        *,
        default: bool | None = None,
    ) -> bool | None:
        value = payload.get(key, default)
        if value is None:
            return None
        if not isinstance(value, bool):
            raise ValueError(f"Command payload field '{key}' must be a boolean when provided")
        return value

    def _summarize_result(self, result: Any) -> Any:
        if result is None:
            return None

        if isinstance(result, (str, int, float, bool)):
            return result

        if isinstance(result, list):
            return list(result)

        if isinstance(result, dict):
            return dict(result)

        return {
            "type": type(result).__name__,
            "repr": repr(result),
        }