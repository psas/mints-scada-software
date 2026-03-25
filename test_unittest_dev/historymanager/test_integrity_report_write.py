from __future__ import annotations

import json
import unittest

from test_unittest_dev.helpers.repo_test_tools import (
    import_module_or_skip,
    make_identity_event,
    temp_project_root,
    write_json,
    write_jsonl,
)


integrity = import_module_or_skip("historymanager.integrity")


class TestIntegrityReportWrite(unittest.TestCase):
    def make_run(self, root, run_id: str):
        raw_dir = root / ".ignitionraw" / run_id
        rawbak_dir = root / ".ignitionrawbak" / run_id
        history_dir = root / "ignitionhistory" / run_id
        for path in (raw_dir, rawbak_dir, history_dir, history_dir / "snapshots"):
            path.mkdir(parents=True, exist_ok=True)
        write_json(history_dir / "metadata.json", {"run_id": run_id, "status": "completed"})
        write_json(history_dir / "complete.json", {"status": "completed"})
        for stream_name, raw_filename in integrity.RAW_STREAM_FILES.items():
            structured_filename = integrity.STRUCTURED_STREAM_FILES[stream_name]
            rows = [make_identity_event(f"{stream_name}-001", 1)]
            write_jsonl(raw_dir / raw_filename, rows)
            write_jsonl(rawbak_dir / raw_filename, rows)
            write_jsonl(history_dir / structured_filename, rows)
        return history_dir

    def test_scan_and_write_run_integrity_creates_json_artifact(self):
        with temp_project_root() as root:
            history_dir = self.make_run(root, "run_write")
            report, report_path = integrity.scan_and_write_run_integrity("run_write", project_root=root)

            self.assertTrue(report_path.is_file())
            self.assertEqual(report_path.parent, history_dir)
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["overall_status"], report["overall_status"])
            self.assertEqual(payload["run_id"], "run_write")

    def test_write_run_integrity_report_requires_history_directory(self):
        with temp_project_root() as root:
            with self.assertRaises(FileNotFoundError):
                integrity.write_run_integrity_report("missing-run", project_root=root, report={"x": 1})
