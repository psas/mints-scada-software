from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LabConfig:
    run_cmd: str | None
    working_dir: Path
    capture_file: Path | None
    main_trace_dir: Path | None
    target_valve_id: str | None
    required_device_ids: list[str]
    inventory_file: Path | None
    backend_log_file: Path | None
    playback_log_file: Path | None
    live_ready_pattern: str | None
    checklist_dev_bypass_pattern: str
    live_log_pattern: str | None
    process_matchers: list[str]
    startup_timeout: float
    action_timeout: float
    shutdown_timeout: float
    artifact_dir: Path
    no_launch: bool
    no_manual_prompts: bool


@dataclass
class PacketRecord:
    raw: str
    direction: str | None = None
    address: str | None = None
    command: str | None = None
    payload_bytes: list[str] = field(default_factory=list)
    sequence: str | None = None
    timestamp: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class GoldenTrace:
    trace_id: str
    description: str
    expected_packets: list[PacketRecord]
    notes: dict[str, Any] = field(default_factory=dict)
