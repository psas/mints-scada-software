"""gui/__init__.py

Lazy public export surface for the GUI package.

This module preserves the historical ``gui`` import surface while deferring
imports of individual GUI modules until a symbol is first accessed. The lazy
resolution avoids importing the full widget stack at package import time and
keeps the public API centralized in one export table.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, tuple[str, str]] = {
    "DecadeSpinBox": (".decadespinbox", "DecadeSpinBox"),
    "AutoPoller": (".autopoller", "AutoPoller"),
    "AutoPollerRow": (".autopollerrow", "AutoPollerRow"),
    "QLoggingHandler": (".qlogginghandler", "QLoggingHandler"),
    "ListView": (".view_list", "ListView"),
    "GraphView": (".view_graph", "GraphView"),
    "ExportView": (".view_export", "ExportView"),
    "ConsoleView": (".view_console", "ConsoleView"),
    "MintsScriptAPI": (".mintsscriptapi", "MintsScriptAPI"),
    "ScriptView": (".view_script", "ScriptView"),
    "ChecklistWindow": (".checklist_window", "ChecklistWindow"),
    "TimelineView": (".timelineview", "TimelineView"),
    "GraphSample": (".graph_data", "GraphSample"),
    "GraphChannelDescriptor": (".graph_data", "GraphChannelDescriptor"),
    "GraphWindow": (".graph_data", "GraphWindow"),
    "build_channel_key": (".graph_data", "build_channel_key"),
    "split_channel_key": (".graph_data", "split_channel_key"),
    "BaseGraphDataProvider": (".graph_provider", "BaseGraphDataProvider"),
    "InMemoryGraphDataProvider": (".graph_provider", "InMemoryGraphDataProvider"),
    "LiveGraphDataProvider": (".live_graph_provider", "LiveGraphDataProvider"),
    "PlaybackGraphDataProvider": (
        ".playback_graph_provider",
        "PlaybackGraphDataProvider",
    ),
    "LiveTelemetryPoller": (".live_telemetry_poller", "LiveTelemetryPoller"),
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    """Resolve a lazily exported GUI symbol on first access.

    Args:
        name: Public attribute name requested from the ``gui`` package.

    Returns:
        The exported object mapped to ``name``.

    Raises:
        AttributeError: The requested name is not part of the package export
            table.
    """
    export = _EXPORTS.get(name)
    if export is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = export
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Return module attributes plus the lazily exported public names.

    Returns:
        A sorted list containing the current module globals and all names
        declared in ``__all__``.
    """
    return sorted(set(globals().keys()) | set(__all__))
