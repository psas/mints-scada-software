from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class FakeCurrentRun:
    run_id: str
    started_wall_time: str
    metadata: dict[str, Any]


class FakeHistoryManager:
    """A small fake that mimics the parts of HistoryManager used by RunController."""

    def __init__(self, *, snapshot_dir: Path):
        self.snapshot_dir = snapshot_dir
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.current_run: FakeCurrentRun | None = None
        self.is_running = False
        self.raw_events: list[tuple[str, dict[str, Any]]] = []
        self.structured_events: list[tuple[str, dict[str, Any]]] = []
        self.snapshots: list[tuple[int, dict[str, Any], Path]] = []
        self._finished_run_ids: list[str] = []

    def start_run(
        self,
        *,
        test_name: str,
        mode: str = "live",
        run_id: str | None = None,
        operator: str | None = None,
        profile_name: str | None = None,
        notes: str | None = None,
        software_git_commit: str | None = None,
        software_branch: str | None = None,
        device_map_version: str | None = None,
        svg_version: str | None = None,
        bus_config=None,
        clock_info=None,
        extra_metadata=None,
    ) -> str:
        run_id_value = run_id or "fake_run_001"
        self.current_run = FakeCurrentRun(
            run_id=run_id_value,
            started_wall_time="2026-03-15T00:00:00Z",
            metadata={
                "mode": mode,
                "test_name": test_name,
                "operator": operator,
                "profile_name": profile_name,
                "notes": notes,
                "software_git_commit": software_git_commit,
                "software_branch": software_branch,
                "device_map_version": device_map_version,
                "svg_version": svg_version,
                "bus_config": dict(bus_config or {}),
                "clock_info": dict(clock_info or {}),
                "extra_metadata": dict(extra_metadata or {}),
            },
        )
        self.is_running = True
        return run_id_value

    def finish_run(self, *, reason: str = "operator_stop") -> str:
        if self.current_run is None:
            raise RuntimeError("No active run")
        run_id = self.current_run.run_id
        self.current_run = None
        self.is_running = False
        self._finished_run_ids.append(run_id)
        return run_id

    def record_raw_event(self, stream_name: str, payload: dict[str, Any]) -> None:
        self.raw_events.append((stream_name, dict(payload)))

    def record_structured_event(self, stream_name: str, payload: dict[str, Any]) -> None:
        self.structured_events.append((stream_name, dict(payload)))

    def write_snapshot(self, index: int, snapshot: dict[str, Any]):
        path = self.snapshot_dir / f"{index:06d}.json"
        path.write_text("snapshot", encoding="utf-8")
        self.snapshots.append((index, dict(snapshot), path))
        return path


class FakeRuntime:
    def __init__(self, *, live_registered: bool = True):
        self.live_registered = live_registered
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def open(self, *args, **kwargs):
        self.calls.append(("open", args, kwargs))
        return "opened"

    def close(self, *args, **kwargs):
        self.calls.append(("close", args, kwargs))
        return "closed"

    def abort(self, *args, **kwargs):
        self.calls.append(("abort", args, kwargs))
        return "aborted"

    def custom_command(self, *args, **kwargs):
        self.calls.append(("custom_command", args, kwargs))
        return {"ok": True}

    def explode(self, *args, **kwargs):
        raise RuntimeError("boom")


class FakeDeviceRegistry:
    def __init__(self, entries: dict[str, dict[str, Any]] | None = None):
        self.entries = dict(entries or {})

    def __contains__(self, device_id: str) -> bool:
        return device_id in self.entries

    def get_meta(self, device_id: str) -> dict[str, Any]:
        return dict(self.entries[device_id]["meta"])

    def get_runtime(self, device_id: str):
        return self.entries[device_id]["runtime"]

    def get_gui_device_presentations(self) -> list[dict[str, Any]]:
        rows = []
        for device_id, entry in self.entries.items():
            meta = dict(entry["meta"])
            meta.setdefault("id", device_id)
            rows.append(meta)
        return rows


class FakeBusManager:
    def __init__(self, *, is_running: bool = True):
        self._is_running = is_running

    @property
    def is_running(self) -> bool:
        return self._is_running
