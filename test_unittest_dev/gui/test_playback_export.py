"""Tests for playback export functions (event-list export path).

Verifies that export_events_jsonl and export_events_csv produce correct
output with ordering that matches the playback seek-index, stream filtering
works, metadata headers are written, and the existing directory-based
helpers remain functional.
"""
from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip, write_json, write_jsonl

export_mod = import_module_or_skip("gui.playback_export")

export_events_jsonl = export_mod.export_events_jsonl
export_events_csv = export_mod.export_events_csv
flatten_event_for_csv = export_mod.flatten_event_for_csv
load_playback_artifacts = export_mod.load_playback_artifacts
export_run_jsonl = export_mod.export_run_jsonl
export_run_csv = export_mod.export_run_csv


def _ev(t: int, **extra) -> dict[str, Any]:
    return {"recorded_at": f"2026-01-01T00:00:{t:02d}Z", **extra}


def _standard_events() -> list[dict[str, Any]]:
    """Mixed-stream events in seek-sorted order."""
    return [
        _ev(1, stream="telemetry_in", device_id="PT-001", event_uid="r:t:1", stream_seq=1),
        _ev(2, stream="telemetry_in", device_id="PT-001", event_uid="r:t:2", stream_seq=2,
            semantic_fields={"pressure_psi": 42.0}),
        _ev(3, stream="command_out", device_id="XV-001", event_uid="r:c:1", stream_seq=1,
            command_name="open", status="ok"),
        _ev(4, stream="telemetry_in", device_id="PT-001", event_uid="r:t:3", stream_seq=3,
            device_state={"runtime_value": 55.5, "online": True}),
        _ev(5, stream="operator_action", event_uid="r:o:1", stream_seq=1,
            event_kind="hold", message="operator hold"),
    ]


# ===================================================================
# JSONL export
# ===================================================================

class TestExportEventsJsonl(unittest.TestCase):

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.outdir = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_basic_jsonl_export(self):
        events = _standard_events()
        out = self.outdir / "out.jsonl"
        count = export_events_jsonl(events, out)
        self.assertEqual(count, 5)
        lines = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
        self.assertEqual(len(lines), 5)

    def test_ordering_matches_input(self):
        events = _standard_events()
        out = self.outdir / "out.jsonl"
        export_events_jsonl(events, out)
        lines = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
        timestamps = [line.get("recorded_at") for line in lines]
        self.assertEqual(timestamps, sorted(timestamps),
                         "Export must preserve input (seek-sorted) ordering")

    def test_stream_filter(self):
        events = _standard_events()
        out = self.outdir / "filtered.jsonl"
        count = export_events_jsonl(events, out, stream_filter={"telemetry_in"})
        self.assertEqual(count, 3)
        lines = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
        for line in lines:
            self.assertEqual(line["stream"], "telemetry_in")

    def test_metadata_header(self):
        events = _standard_events()
        out = self.outdir / "meta.jsonl"
        meta = {"run_id": "test-run", "test_name": "demo"}
        export_events_jsonl(events, out, metadata=meta)
        lines = out.read_text().splitlines()
        header = json.loads(lines[0])
        self.assertTrue(header.get("_export_metadata"))
        self.assertEqual(header["run_id"], "test-run")
        self.assertIn("exported_at", header)
        # Data events follow the header
        self.assertEqual(len(lines), 6)  # 1 header + 5 events

    def test_no_metadata_means_no_header(self):
        events = [_ev(1, stream="telemetry_in")]
        out = self.outdir / "no_meta.jsonl"
        export_events_jsonl(events, out, metadata=None)
        lines = out.read_text().splitlines()
        first = json.loads(lines[0])
        self.assertNotIn("_export_metadata", first)

    def test_empty_events(self):
        out = self.outdir / "empty.jsonl"
        count = export_events_jsonl([], out)
        self.assertEqual(count, 0)
        self.assertTrue(out.exists())

    def test_creates_parent_directories(self):
        out = self.outdir / "sub" / "dir" / "out.jsonl"
        export_events_jsonl([_ev(1)], out)
        self.assertTrue(out.exists())


# ===================================================================
# CSV export
# ===================================================================

class TestExportEventsCsv(unittest.TestCase):

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.outdir = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_basic_csv_export(self):
        events = _standard_events()
        out = self.outdir / "out.csv"
        count = export_events_csv(events, out)
        self.assertEqual(count, 5)
        with out.open(newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.assertEqual(len(rows), 5)

    def test_csv_has_expected_columns(self):
        events = _standard_events()
        out = self.outdir / "cols.csv"
        export_events_csv(events, out)
        with out.open(newline="") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames
        for col in ("recorded_at", "stream", "event_uid", "device_id"):
            self.assertIn(col, fields)

    def test_csv_ordering_matches_input(self):
        events = _standard_events()
        out = self.outdir / "order.csv"
        export_events_csv(events, out)
        with out.open(newline="") as f:
            reader = csv.DictReader(f)
            timestamps = [row["recorded_at"] for row in reader]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_csv_stream_filter(self):
        events = _standard_events()
        out = self.outdir / "filtered.csv"
        count = export_events_csv(events, out, stream_filter={"command_out"})
        self.assertEqual(count, 1)
        with out.open(newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.assertEqual(rows[0]["stream"], "command_out")

    def test_semantic_fields_flattened(self):
        events = _standard_events()
        out = self.outdir / "semantic.csv"
        export_events_csv(events, out)
        with out.open(newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # Event at T=2 has semantic_fields.pressure_psi
        row_t2 = rows[1]
        self.assertEqual(row_t2.get("semantic_pressure_psi"), "42.0")

    def test_device_state_flattened(self):
        events = _standard_events()
        out = self.outdir / "devstate.csv"
        export_events_csv(events, out)
        with out.open(newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # Event at T=4 has device_state.runtime_value
        row_t4 = rows[3]
        self.assertEqual(row_t4.get("device_state_runtime_value"), "55.5")

    def test_empty_events(self):
        out = self.outdir / "empty.csv"
        count = export_events_csv([], out)
        self.assertEqual(count, 0)
        self.assertTrue(out.exists())


# ===================================================================
# flatten_event_for_csv
# ===================================================================

class TestFlattenEventForCsv(unittest.TestCase):

    def test_basic_fields_extracted(self):
        event = _ev(1, stream="telemetry_in", device_id="PT-001", event_uid="uid1")
        flat = flatten_event_for_csv(event)
        self.assertEqual(flat["stream"], "telemetry_in")
        self.assertEqual(flat["device_id"], "PT-001")
        self.assertEqual(flat["event_uid"], "uid1")

    def test_semantic_fields_prefixed(self):
        event = _ev(1, semantic_fields={"pressure_psi": 42.0, "temp_c": 20.0})
        flat = flatten_event_for_csv(event)
        self.assertEqual(flat["semantic_pressure_psi"], 42.0)
        self.assertEqual(flat["semantic_temp_c"], 20.0)

    def test_device_state_prefixed(self):
        event = _ev(1, device_state={"runtime_value": 100, "online": True})
        flat = flatten_event_for_csv(event)
        self.assertEqual(flat["device_state_runtime_value"], 100)
        self.assertEqual(flat["device_state_online"], True)

    def test_missing_fields_are_none(self):
        flat = flatten_event_for_csv({"recorded_at": "2026-01-01T00:00:00Z"})
        self.assertIsNone(flat["stream"])
        self.assertIsNone(flat["device_id"])


# ===================================================================
# Directory-based export (existing helpers, smoke test)
# ===================================================================

class TestDirectoryBasedExport(unittest.TestCase):
    """Smoke test for the original directory-reading export functions."""

    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.run_dir = Path(self.tmpdir.name) / "test-run"
        self.run_dir.mkdir()
        write_json(self.run_dir / "metadata.json", {
            "run_id": "test-run",
            "start_wall_time": "2026-01-01T00:00:00Z",
        })
        write_jsonl(self.run_dir / "merged.jsonl", _standard_events())

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_load_playback_artifacts(self):
        metadata, events = load_playback_artifacts(self.run_dir)
        self.assertEqual(metadata["run_id"], "test-run")
        self.assertEqual(len(events), 5)

    def test_export_run_jsonl(self):
        out = Path(self.tmpdir.name) / "export.jsonl"
        result = export_run_jsonl(self.run_dir, out)
        self.assertTrue(Path(result).exists())
        lines = Path(result).read_text().splitlines()
        self.assertEqual(len(lines), 5)

    def test_export_run_csv(self):
        out = Path(self.tmpdir.name) / "export.csv"
        result = export_run_csv(self.run_dir, out)
        self.assertTrue(Path(result).exists())
        with open(result, newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 5)
