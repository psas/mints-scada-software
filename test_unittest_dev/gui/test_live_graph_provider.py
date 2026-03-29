from __future__ import annotations

from gui.live_graph_provider import LiveGraphDataProvider


def test_ingest_state_snapshot_extracts_numeric_runtime_values():
    provider = LiveGraphDataProvider()
    snapshot = {
        "wall_time": "2026-03-27T12:00:00Z",
        "device_registry": {
            "devices": [
                {"id": "pt-1", "name": "PT 1", "unit": "psi"},
                {"id": "xv-1", "name": "XV 1"},
            ]
        },
        "device_runtime": {
            "by_id": {
                "pt-1": {"runtime_value": 123.4, "runtime_time": 10.0},
                "xv-1": {"runtime_value": "not-numeric"},
            }
        },
    }

    appended = provider.ingest_state_snapshot(snapshot)

    assert len(appended) == 1
    sample = appended[0]
    assert sample.channel_key == "pt-1"
    assert sample.value == 123.4
    assert sample.display_name == "PT 1"
    assert sample.unit == "psi"

    descriptors = provider.get_channel_descriptors()
    assert [d.channel_key for d in descriptors] == ["pt-1", "xv-1"]


def test_ingest_structured_event_accepts_scalar_or_mapping_values():
    provider = LiveGraphDataProvider()
    appended = provider.ingest_structured_event({
        "wall_time": "2026-03-27T12:00:01Z",
        "telemetry": {
            "pt-1": 10.5,
            "pt-2": {"value": 20, "time": 33.0},
            "bad": {"value": "abc"},
        },
    })

    assert [sample.channel_key for sample in appended] == ["pt-1", "pt-2"]
    samples = provider.get_samples(channel_keys=["pt-1", "pt-2"])
    by_key = {sample.channel_key: sample for sample in samples}
    assert len(by_key) == 2
    assert by_key["pt-1"].value == 10.5
    assert by_key["pt-2"].value == 20.0
