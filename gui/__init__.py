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
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    export = _EXPORTS.get(name)
    if export is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = export
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(__all__))


