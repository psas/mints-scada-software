"""Tests for sort_merged_history_for_run() ordering correctness.

Verifies the sort key is (recorded_at, global_seq, stream_seq, event_uid)
and that the function produces a stable, deterministic re-ordering of
merged.jsonl contents.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip


manager_module = import_module_or_skip("historymanager.manager")
paths_module = import_module_or_skip("historymanager.paths")

HistoryManager = manager_module.HistoryManager
get_base_dirs = paths_module.get_base_dirs


def _write_merged(project_root: Path, run_id: str, events: list[dict]) -> Path:
    """Write a merged.jsonl file at the expected archive path."""
    base_dirs = get_base_dirs(project_root)
    history_dir = base_dirs.history_root / run_id
    history_dir.mkdir(parents=True, exist_ok=True)
    merged_path = history_dir / "merged.jsonl"
    with merged_path.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False, sort_keys=False))
            f.write("\n")
    return merged_path


def _read_merged(merged_path: Path) -> list[dict]:
    events = []
    with merged_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


class TestMergedSortOrder(unittest.TestCase):

    def _make_manager(self, project_root: Path) -> HistoryManager:
        return HistoryManager(
            project_root=project_root,
            enable_raw_writer=False,
            enable_rawbak_writer=False,
            enable_structured_writer=False,
        )

    def test_sorts_by_recorded_at_primary(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = [
                {"recorded_at": "2026-01-01T00:00:03Z", "label": "c"},
                {"recorded_at": "2026-01-01T00:00:01Z", "label": "a"},
                {"recorded_at": "2026-01-01T00:00:02Z", "label": "b"},
            ]
            merged_path = _write_merged(root, "run-sort-1", events)

            mgr = self._make_manager(root)
            mgr.sort_merged_history_for_run("run-sort-1")

            result = _read_merged(merged_path)
            self.assertEqual([e["label"] for e in result], ["a", "b", "c"])

    def test_global_seq_breaks_tie_when_recorded_at_equal(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = [
                {"recorded_at": "2026-01-01T00:00:01Z", "global_seq": 3, "label": "second"},
                {"recorded_at": "2026-01-01T00:00:01Z", "global_seq": 1, "label": "first"},
                {"recorded_at": "2026-01-01T00:00:01Z", "global_seq": 5, "label": "third"},
            ]
            merged_path = _write_merged(root, "run-sort-2", events)

            mgr = self._make_manager(root)
            mgr.sort_merged_history_for_run("run-sort-2")

            result = _read_merged(merged_path)
            self.assertEqual([e["label"] for e in result], ["first", "second", "third"])

    def test_stream_seq_breaks_tie_after_global_seq(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = [
                {"recorded_at": "2026-01-01T00:00:01Z", "global_seq": 1, "stream_seq": 5, "label": "b"},
                {"recorded_at": "2026-01-01T00:00:01Z", "global_seq": 1, "stream_seq": 2, "label": "a"},
            ]
            merged_path = _write_merged(root, "run-sort-3", events)

            mgr = self._make_manager(root)
            mgr.sort_merged_history_for_run("run-sort-3")

            result = _read_merged(merged_path)
            self.assertEqual([e["label"] for e in result], ["a", "b"])

    def test_missing_global_seq_sorts_as_zero(self):
        """Events without global_seq should sort before events with global_seq
        at the same recorded_at (since missing → 0)."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = [
                {"recorded_at": "2026-01-01T00:00:01Z", "global_seq": 2, "label": "has-seq"},
                {"recorded_at": "2026-01-01T00:00:01Z", "label": "no-seq"},
            ]
            merged_path = _write_merged(root, "run-sort-4", events)

            mgr = self._make_manager(root)
            mgr.sort_merged_history_for_run("run-sort-4")

            result = _read_merged(merged_path)
            self.assertEqual([e["label"] for e in result], ["no-seq", "has-seq"])

    def test_sort_is_stable_and_idempotent(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = [
                {"recorded_at": "2026-01-01T00:00:02Z", "global_seq": 2, "label": "b"},
                {"recorded_at": "2026-01-01T00:00:01Z", "global_seq": 1, "label": "a"},
                {"recorded_at": "2026-01-01T00:00:03Z", "global_seq": 3, "label": "c"},
            ]
            merged_path = _write_merged(root, "run-sort-5", events)

            mgr = self._make_manager(root)
            mgr.sort_merged_history_for_run("run-sort-5")
            first_pass = _read_merged(merged_path)

            mgr.sort_merged_history_for_run("run-sort-5")
            second_pass = _read_merged(merged_path)

            self.assertEqual(first_pass, second_pass)

    def test_missing_file_returns_none(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            mgr = self._make_manager(root)
            result = mgr.sort_merged_history_for_run("nonexistent-run")
            self.assertIsNone(result)

    def test_empty_file_produces_empty_output(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            merged_path = _write_merged(root, "run-sort-empty", [])

            mgr = self._make_manager(root)
            mgr.sort_merged_history_for_run("run-sort-empty")

            result = _read_merged(merged_path)
            self.assertEqual(result, [])
