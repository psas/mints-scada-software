from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class GatewayRuntimeConfig:
    """Runtime configuration for the gateway process."""

    project_root: Path
    socket_path: Path
    backend_socket_path: Path
    idle_sleep_s: float = 0.25