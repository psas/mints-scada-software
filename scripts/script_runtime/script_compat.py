# scripts/script_runtime/script_compat.py

"""Compatibility facades for legacy script execution in the subprocess host.

This module exposes the minimal legacy ``mints`` surface that older scripts can
use when they are executed through the subprocess-based script runtime. It
proxies supported device commands and callbacks into host-provided runtime
hooks, while rejecting deprecated UI-facing members that are no longer
available in the backend-owned script host.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

try:
    from scripts.script_runtime.script_contract import (
        DEPRECATED_MINTS_MEMBERS,
        LEGACY_SCRIPT_SUPPORTED_SURFACE,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback for isolated scaffold testing
    DEPRECATED_MINTS_MEMBERS = ("graph", "exporter", "autopoller")
    LEGACY_SCRIPT_SUPPORTED_SURFACE = ("print", "wait", "abort", "mints.devices")


class UnsupportedLegacyScriptMember(AttributeError):
    """Raised when legacy scripts access a deprecated ``mints`` member."""


@dataclass
class LegacyDeviceProxy:
    """Proxy a single ``mints.devices[...]`` entry into command callbacks.

    The proxy is intentionally dynamic: any non-private attribute access is
    treated as a legacy device command name and converted into a call to the
    host runtime's ``command_callback``.

    Args:
        device_id: Canonical device identifier represented by this proxy.
        command_callback: Host callback that receives normalized legacy device
            command invocations.
    """

    device_id: str
    command_callback: Callable[..., None]

    def __getattr__(self, name: str) -> Any:
        """Build a callable that forwards legacy device commands to the host.

        Args:
            name: Legacy method name accessed on the device proxy.

        Returns:
            A callable that forwards the invoked command name, positional
            arguments, and keyword arguments to ``command_callback``.

        Raises:
            AttributeError: If ``name`` is private.
        """
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
    """Expose the supported subprocess compatibility surface for ``mints``.

    Args:
        devices: Mapping of canonical device identifiers to device proxies that
            legacy scripts can access through ``mints.devices``.
    """

    devices: dict[str, LegacyDeviceProxy] = field(default_factory=dict)

    def __getattr__(self, name: str) -> Any:
        """Reject deprecated legacy members that are unavailable in the host.

        Args:
            name: Attribute name requested by the legacy script.

        Returns:
            Never returns successfully for unknown attributes.

        Raises:
            UnsupportedLegacyScriptMember: If the script requests a known
                deprecated legacy UI/display member.
            AttributeError: If the attribute is otherwise unsupported.
        """
        if name in DEPRECATED_MINTS_MEMBERS:
            raise UnsupportedLegacyScriptMember(
                f"Legacy script member {name!r} is not available in the subprocess host"
            )
        raise AttributeError(name)


@dataclass
class ScriptHostCallbacks:
    """Bundle the host callbacks used by the subprocess legacy runtime facade.

    Args:
        print_callback: Callback used for legacy ``print`` calls.
        wait_callback: Callback used for legacy ``wait`` calls.
        abort_callback: Callback used for legacy ``abort`` calls.
        command_callback: Callback used for legacy device command calls through
            ``mints.devices``.
    """

    print_callback: Callable[..., None]
    wait_callback: Callable[[float], None]
    abort_callback: Callable[..., None]
    command_callback: Callable[..., None]


class LegacyScriptRuntimeFacade:
    """Provide the supported legacy script surface for subprocess execution.

    The facade exposes ``print()``, ``wait()``, ``abort()``, and
    ``mints.devices[...]`` so older scripts can run against the backend-owned
    subprocess host without depending on removed GUI-facing APIs.
    """

    def __init__(
        self,
        *,
        device_ids: Iterable[str] | None = None,
        callbacks: ScriptHostCallbacks,
    ) -> None:
        """Build the compatibility facade and seed legacy device proxies.

        Args:
            device_ids: Iterable of canonical device identifiers that should be
                exposed through ``mints.devices``.
            callbacks: Host callback bundle used to execute supported legacy
                operations.
        """
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
        """Forward a legacy ``print`` call to the host runtime callback.

        Args:
            *args: Positional arguments forwarded to the print callback.
            **kwargs: Keyword arguments forwarded to the print callback.
        """
        self._callbacks.print_callback(*args, **kwargs)

    def wait(self, seconds: float) -> None:
        """Forward a legacy ``wait`` call to the host runtime callback.

        Args:
            seconds: Delay duration requested by the script, in seconds.
        """
        self._callbacks.wait_callback(float(seconds))

    def abort(self, *args: Any, **kwargs: Any) -> None:
        """Forward a legacy ``abort`` call to the host runtime callback.

        Args:
            *args: Positional arguments forwarded to the abort callback.
            **kwargs: Keyword arguments forwarded to the abort callback.
        """
        self._callbacks.abort_callback(*args, **kwargs)


def default_wait_callback(seconds: float) -> None:
    """Sleep for a non-negative number of seconds.

    Args:
        seconds: Requested sleep duration in seconds.

    Returns:
        None.
    """
    time.sleep(max(0.0, float(seconds)))
