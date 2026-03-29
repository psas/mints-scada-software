from __future__ import annotations

import json
from pathlib import Path

from gui.playback_graph_provider import PlaybackGraphDataProvider


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_playback_provider_loads_samples_from_ignitionhistory(tmp_path: Path):
    history_dir = tmp_path / "run-1"
    history_dir.mkdir()
    snapshots = history_dir / "snapshots"
    snapshots.mkdir()

    _write_json(history_dir / "metadata.json", {
        "run_id": "run-1",
        "start_wall_time": "2026-03-27T00:00:00+00:00",
    })
    _write_json(snapshots / "000000.json", {
        "state": {
            "device_registry": {
                "devices": [
                    {"id": "pt-1", "name": "Pressure 1", "unit": "psi"},
                ]
            }
        }
    })
    (history_dir / "merged.jsonl").write_text(
        "\n".join([
            json.dumps({
                "wall_time": "2026-03-27T00:00:05+00:00",
                "telemetry": {"pt-1": {"value": 12.5}},
            }),
            json.dumps({
                "wall_time": "2026-03-27T00:00:07+00:00",
                "device_runtime": {"by_id": {"pt-1": {"runtime_value": 15.0}}},
            }),
        ]),
        encoding="utf-8",
    )

    provider = PlaybackGraphDataProvider()
    provider.load_from_payload({
        "history_dir": str(history_dir),
        "run_id": "run-1",
        "playback_source": "native",
    })

    samples = provider.get_samples(channel_keys=["pt-1"], start_ts=0.0, end_ts=10.0)
    assert [round(sample.timestamp, 3) for sample in samples] == [5.0, 7.0]
    assert [sample.value for sample in samples] == [12.5, 15.0]
    descriptors = provider.get_channel_descriptors()
    assert descriptors[0].display_name == "Pressure 1"
    assert descriptors[0].unit == "psi"


def test_playback_provider_reads_rebuild_artifacts(tmp_path: Path):
    history_dir = tmp_path / "run-2"
    history_dir.mkdir()
    snapshots = history_dir / "snapshots_rebuild"
    snapshots.mkdir()

    _write_json(history_dir / "metadata.json", {"run_id": "run-2", "start_wall_time": "2026-03-27T00:00:00+00:00"})
    _write_json(snapshots / "000000.json", {"state": {"device_registry": {"devices": []}}})
    (history_dir / "merged.rebuild.jsonl").write_text(
        json.dumps({
            "wall_time": "2026-03-27T00:00:02+00:00",
            "telemetry": {"valve-1": {"state": "open"}},
        }),
        encoding="utf-8",
    )

    provider = PlaybackGraphDataProvider()
    provider.load_from_payload({
        "history_dir": str(history_dir),
        "run_id": "run-2",
        "playback_source": "rebuild",
    })

    samples = provider.get_samples(channel_keys=["valve-1"], start_ts=0.0, end_ts=10.0)
    assert len(samples) == 1
    assert samples[0].value == 1.0
