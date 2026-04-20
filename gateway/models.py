"""gateway/models.py

Gateway runtime data models.

This module defines small typed containers shared by the gateway bootstrap and
service layers to carry resolved runtime configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class GatewayRuntimeConfig:
    """Resolved runtime configuration for the gateway process.

    Attributes:
        project_root: Absolute project root used to resolve runtime resources
            and history paths.
        socket_path: Unix domain socket path served by the gateway IPC server.
        backend_socket_path: Unix domain socket path used to reach the backend
            service.
        idle_sleep_s: Idle sleep interval used by the gateway service loop when
            no work is available.
    """

    project_root: Path
    socket_path: Path
    backend_socket_path: Path
    idle_sleep_s: float = 0.25
