# backend/__init__.py

"""Public backend package exports for the backend-first runtime layer.

This package surface re-exports the main backend coordination and state
components used by callers that import from `backend` directly.
"""

from .service import BackendService
from .ipc_models import IPCMessage
from .state_store import StateStore
from .run_controller import RunController
from .bus_manager import BusManager
from .device_registry import DeviceRegistry
from .reducer import Reducer
from .structured_builder import StructuredEventBuilder
from .command_router import CommandRouter
from .script_runner import ScriptRunner
from .health import HealthPublisher

__all__ = [
    "BackendService",
    "IPCMessage",
    "StateStore",
    "RunController",
    "BusManager",
    "DeviceRegistry",
    "Reducer",
    "StructuredEventBuilder",
    "CommandRouter",
    "ScriptRunner",
    "HealthPublisher",
]
