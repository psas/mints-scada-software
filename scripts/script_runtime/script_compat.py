from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

try:
    from scripts.script_runtime.script_contract import (
        DEPRECATED_MINTS_MEMBERS,
        LEGACY_SCRIPT_SUPPORTED_SURFACE,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback for isolated scaffold testing
    DEPRECATED_MINTS_MEMBERS = ("graph", "exporter", "autopoller")
    LEGACY_SCRIPT_SUPPORTED_SURFACE = ("print", "wait", "abort", "mints.devices")


class UnsupportedLegacyScriptMember(AttributeError):
    """Raised when a deprecated legacy UI/display API is accessed in the host scaffold."""


@dataclass
class LegacyMintsProxy:
    """Future subprocess-facing compatibility surface for ``mints``.

    Commit4 scope is intentionally narrow:
    - preserve ``mints.devices`` as real data
    - preserve legacy deprecated member names as clear placeholders
    - do not implement display-oriented APIs yet
    """

    devices: dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, name: str) -> Any:
        if name in DEPRECATED_MINTS_MEMBERS:
            raise UnsupportedLegacyScriptMember(
                f"Legacy script member {name!r} is not available in the subprocess scaffold yet"
            )
        raise AttributeError(name)


@dataclass
class ScriptHostCallbacks:
    """Runtime callback hooks that the future host execution path will use."""

    print_callback: Callable[..., None]
    wait_callback: Callable[[float], None]
    abort_callback: Callable[..., None]


class LegacyScriptRuntimeFacade:
    """Minimal compatibility facade for future subprocess execution.

    This scaffold is deliberately small but real. It exposes the preserved script
    surface and keeps deprecated members out of the long-term API.
    """

    def __init__(
        self,
        *,
        devices: Mapping[str, Any] | None = None,
        callbacks: ScriptHostCallbacks,
    ) -> None:
        self.mints = LegacyMintsProxy(devices=dict(devices or {}))
        self._callbacks = callbacks
        self.supported_surface = tuple(LEGACY_SCRIPT_SUPPORTED_SURFACE)

    def print(self, *args: Any, **kwargs: Any) -> None:
        self._callbacks.print_callback(*args, **kwargs)

    def wait(self, seconds: float) -> None:
        self._callbacks.wait_callback(float(seconds))

    def abort(self, *args: Any, **kwargs: Any) -> None:
        self._callbacks.abort_callback(*args, **kwargs)



def default_wait_callback(seconds: float) -> None:
    time.sleep(max(0.0, float(seconds)))
