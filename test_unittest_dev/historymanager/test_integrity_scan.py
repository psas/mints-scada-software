from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import (
    import_module_or_skip,
    make_identity_event,
    temp_project_root,
    write_json,
    write_jsonl,
)


integrity = import_module_or_skip("historymanager.integrity")


class TestIntegrityScan(unittest.TestCase):
    def make_run_layout(self, root, run_id: str):
        raw_dir = root / ".ignitionraw" / run_id
        rawbak_dir = root / ".ignitionrawbak" / run_id
        history_dir = root / "ignitionhistory" / run_id
        for path in (raw_dir, rawbak_dir, history_dir, history_dir / "snapshots"):
            path.mkdir(parents=True, exist_ok=True)
        write_json(history_dir / "metadata.json", {"run_id": run_id, "status": "completed"})
        write_json(history_dir / "complete.json", {"status": "completed"})
        return raw_dir, rawbak_dir, history_dir

    def populate_all_streams(self, raw_dir, rawbak_dir, history_dir):
        for stream_name, raw_filename in integrity.RAW_STREAM_FILES.items():
            structured_filename = integrity.STRUCTURED_STREAM_FILES[stream_name]
            rows = [make_identity_event(f"{stream_name}-001", 1)]
            write_jsonl(raw_dir / raw_filename, rows)
            write_jsonl(rawbak_dir / raw_filename, rows)
            write_jsonl(history_dir / structured_filename, rows)

    def test_scan_reports_ok_for_matching_native_archive(self):
        with temp_project_root() as root:
            raw_dir, rawbak_dir, history_dir = self.make_run_layout(root, "run_ok")
            self.populate_all_streams(raw_dir, rawbak_dir, history_dir)

            report = integrity.scan_run_integrity("run_ok", project_root=root)

            self.assertEqual(report["overall_status"], "ok")
            self.assertEqual(report["badge"], "green")
            self.assertEqual(report["summary_message"], "All data matches natively")

    def test_scan_reports_partial_when_one_source_is_missing(self):
        with temp_project_root() as root:
            raw_dir, rawbak_dir, history_dir = self.make_run_layout(root, "run_partial")
            self.populate_all_streams(raw_dir, rawbak_dir, history_dir)

            # Remove rawbak to simulate a missing mirrored archive.
            for child in rawbak_dir.iterdir():
                child.unlink()
            rawbak_dir.rmdir()

            report = integrity.scan_run_integrity("run_partial", project_root=root)

            self.assertEqual(report["overall_status"], "partial")
            self.assertEqual(report["badge"], "yellow")
            self.assertIn("rawbak", report["summary_message"])

    def test_scan_reports_mismatch_when_hashes_differ(self):
        with temp_project_root() as root:
            raw_dir, rawbak_dir, history_dir = self.make_run_layout(root, "run_mismatch")
            self.populate_all_streams(raw_dir, rawbak_dir, history_dir)

            bad_row = [make_identity_event("telemetry_in-001", 1, canonical_hash="different-hash")]
            write_jsonl(history_dir / integrity.STRUCTURED_STREAM_FILES["telemetry_in"], bad_row)

            report = integrity.scan_run_integrity("run_mismatch", project_root=root)

            self.assertEqual(report["overall_status"], "mismatch")
            self.assertEqual(report["badge"], "red")
            self.assertEqual(report["stream_reports"]["telemetry_in"]["status"], "mismatch")
