from __future__ import annotations

import json
from pathlib import Path

from gui.graph_data import GraphChannelDescriptor, GraphSample
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


# ---------------------------------------------------------------------------
# Playback cursor tests
# ---------------------------------------------------------------------------

def _make_provider_with_samples() -> PlaybackGraphDataProvider:
    """Build a provider with samples at t=1, 3, 5, 7, 9 for channel 'ch'."""
    provider = PlaybackGraphDataProvider()
    provider.register_channel(GraphChannelDescriptor(
        channel_key="ch", display_name="Channel", unit="V", source="test",
    ))
    provider.ingest_samples([
        GraphSample(timestamp=float(t), channel_key="ch", value=float(t * 10), source="test")
        for t in (1, 3, 5, 7, 9)
    ])
    return provider


def test_cursor_default_is_none():
    provider = PlaybackGraphDataProvider()
    assert provider.playback_cursor is None


def test_cursor_clips_get_samples():
    provider = _make_provider_with_samples()
    provider.set_playback_cursor(5.0)

    samples = provider.get_samples(channel_keys=["ch"])
    timestamps = [s.timestamp for s in samples]
    assert timestamps == [1.0, 3.0, 5.0]


def test_cursor_clips_even_when_end_ts_is_larger():
    provider = _make_provider_with_samples()
    provider.set_playback_cursor(5.0)

    samples = provider.get_samples(channel_keys=["ch"], start_ts=0.0, end_ts=100.0)
    timestamps = [s.timestamp for s in samples]
    assert timestamps == [1.0, 3.0, 5.0]


def test_cursor_none_returns_all():
    provider = _make_provider_with_samples()
    provider.set_playback_cursor(None)

    samples = provider.get_samples(channel_keys=["ch"])
    assert len(samples) == 5


def test_cursor_advance_reveals_more_data():
    provider = _make_provider_with_samples()

    provider.set_playback_cursor(3.0)
    assert len(provider.get_samples(channel_keys=["ch"])) == 2

    provider.set_playback_cursor(7.0)
    assert len(provider.get_samples(channel_keys=["ch"])) == 4


def test_cursor_seek_backward_hides_future_data():
    provider = _make_provider_with_samples()

    provider.set_playback_cursor(9.0)
    assert len(provider.get_samples(channel_keys=["ch"])) == 5

    provider.set_playback_cursor(3.0)
    samples = provider.get_samples(channel_keys=["ch"])
    timestamps = [s.timestamp for s in samples]
    assert timestamps == [1.0, 3.0]


def test_cursor_zero_returns_no_samples():
    provider = _make_provider_with_samples()
    provider.set_playback_cursor(0.0)

    samples = provider.get_samples(channel_keys=["ch"])
    assert samples == []


def test_cursor_does_not_affect_explicit_end_ts_when_smaller():
    """If caller passes end_ts < cursor, the caller's bound wins."""
    provider = _make_provider_with_samples()
    provider.set_playback_cursor(9.0)

    samples = provider.get_samples(channel_keys=["ch"], end_ts=3.0)
    timestamps = [s.timestamp for s in samples]
    assert timestamps == [1.0, 3.0]


def test_cursor_reset_on_reset_run():
    provider = _make_provider_with_samples()
    provider.set_playback_cursor(5.0)
    provider.reset_run()
    assert provider.playback_cursor is None


def test_cursor_clamps_negative_to_zero():
    provider = _make_provider_with_samples()
    provider.set_playback_cursor(-10.0)
    assert provider.playback_cursor == 0.0
