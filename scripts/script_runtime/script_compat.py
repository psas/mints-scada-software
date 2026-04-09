# scripts/script_runtime/script_compat.py

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

try:
    from scripts.script_runtime.script_contract import (
        DEPRECATED_MINTS_MEMBERS,
        LEGACY_SCRIPT_SUPPORTED_SURFACE,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback for isolated scaffold testing
    DEPRECATED_MINTS_MEMBERS = ("graph", "exporter", "autopoller")
    LEGACY_SCRIPT_SUPPORTED_SURFACE = ("print", "wait", "abort", "mints.devices")


class UnsupportedLegacyScriptMember(AttributeError):
    """Raised when a deprecated legacy UI/display API is accessed in the host runtime."""


@dataclass
class LegacyDeviceProxy:
    """Subprocess-safe proxy for a single legacy ``mints.devices[...]`` entry."""

    device_id: str
    command_callback: Callable[..., None]

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def call_device_method(*args: Any, **kwargs: Any) -> None:
            self.command_callback(
                device_id=self.device_id,
                command_name=name,
                command_args=list(args),
                command_kwargs=dict(kwargs),
            )

        return call_device_method


@dataclass
class LegacyMintsProxy:
    """Future subprocess-facing compatibility surface for ``mints``."""

    devices: dict[str, LegacyDeviceProxy] = field(default_factory=dict)

    def __getattr__(self, name: str) -> Any:
        if name in DEPRECATED_MINTS_MEMBERS:
            raise UnsupportedLegacyScriptMember(
                f"Legacy script member {name!r} is not available in the subprocess host"
            )
        raise AttributeError(name)


@dataclass
class ScriptHostCallbacks:
    """Runtime callback hooks that the subprocess host execution path uses."""

    print_callback: Callable[..., None]
    wait_callback: Callable[[float], None]
    abort_callback: Callable[..., None]
    command_callback: Callable[..., None]


class LegacyScriptRuntimeFacade:
    """Minimal compatibility facade for subprocess legacy script execution."""

    def __init__(
        self,
        *,
        device_ids: Iterable[str] | None = None,
        callbacks: ScriptHostCallbacks,
    ) -> None:
        self._callbacks = callbacks
        self.mints = LegacyMintsProxy(
            devices={
                str(device_id): LegacyDeviceProxy(
                    device_id=str(device_id),
                    command_callback=self._callbacks.command_callback,
                )
                for device_id in (device_ids or [])
            }
        )
        self.supported_surface = tuple(LEGACY_SCRIPT_SUPPORTED_SURFACE)

    def print(self, *args: Any, **kwargs: Any) -> None:
        self._callbacks.print_callback(*args, **kwargs)

    def wait(self, seconds: float) -> None:
        self._callbacks.wait_callback(float(seconds))

    def abort(self, *args: Any, **kwargs: Any) -> None:
        self._callbacks.abort_callback(*args, **kwargs)



def default_wait_callback(seconds: float) -> None:
    time.sleep(max(0.0, float(seconds)))
