"""Tests for RunController playback-related correctness:

- Initial snapshot recorded_at is anchored to started_wall_time.
- maybe_write_periodic_snapshot() respects interval, negative delta, and boundary.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from test_unittest_dev.helpers.fakes import FakeHistoryManager
from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip


state_store_module = import_module_or_skip("backend.state_store")
run_controller_module = import_module_or_skip("backend.run_controller")

StateStore = state_store_module.StateStore
RunController = run_controller_module.RunController


class TestInitialSnapshotRecordedAt(unittest.TestCase):
    """The initial snapshot must carry recorded_at == started_wall_time so that
    the snapshot file and the periodic-snapshot timer share the same anchor."""

    def _make(self):
        tempdir = TemporaryDirectory()
        history = FakeHistoryManager(snapshot_dir=Path(tempdir.name) / "snapshots")
        store = StateStore(
            service_name="backend_service",
            backend_started_at="2026-03-15T00:00:00Z",
        )
        controller = RunController(history_manager=history, state_store=store)
        return tempdir, history, store, controller

    def test_initial_snapshot_has_recorded_at_matching_started_wall_time(self):
        tempdir, history, _store, controller = self._make()
        self.addCleanup(tempdir.cleanup)

        controller.start_run(test_name="alignment check", mode="live")

        # FakeHistoryManager.snapshots is list[(index, payload_dict, path)]
        self.assertEqual(len(history.snapshots), 1)
        _index, snapshot_payload, _path = history.snapshots[0]
        self.assertIn("recorded_at", snapshot_payload)
        self.assertEqual(
            snapshot_payload["recorded_at"],
            history.current_run.started_wall_time,
        )

    def test_periodic_timer_anchor_equals_initial_snapshot_recorded_at(self):
        tempdir, history, _store, controller = self._make()
        self.addCleanup(tempdir.cleanup)

        controller.start_run(test_name="anchor check", mode="live")

        self.assertEqual(
            controller._last_periodic_snapshot_recorded_at,
            history.current_run.started_wall_time,
        )


class TestPeriodicSnapshotDeltaBehavior(unittest.TestCase):
    """Verify maybe_write_periodic_snapshot() interval logic including
    negative-delta (out-of-order event) handling."""

    def _make(self, interval: float = 5.0):
        tempdir = TemporaryDirectory()
        history = FakeHistoryManager(snapshot_dir=Path(tempdir.name) / "snapshots")
        store = StateStore(
            service_name="backend_service",
            backend_started_at="2026-03-15T00:00:00Z",
        )
        controller = RunController(history_manager=history, state_store=store)
        controller._periodic_snapshot_interval_seconds = interval
        return tempdir, history, store, controller

    def test_below_interval_does_not_write(self):
        tempdir, history, store, controller = self._make(interval=5.0)
        self.addCleanup(tempdir.cleanup)

        controller.start_run(test_name="t", mode="live")
        initial_count = len(history.snapshots)

        # 3 seconds after start — should NOT trigger a snapshot
        result = controller.maybe_write_periodic_snapshot(
            snapshot=store.get_snapshot(),
            event_recorded_at="2026-03-15T00:00:03Z",
        )
        self.assertIsNone(result)
        self.assertEqual(len(history.snapshots), initial_count)

    def test_at_interval_boundary_writes(self):
        tempdir, history, store, controller = self._make(interval=5.0)
        self.addCleanup(tempdir.cleanup)

        controller.start_run(test_name="t", mode="live")
        initial_count = len(history.snapshots)

        # Exactly 5 seconds — should write
        result = controller.maybe_write_periodic_snapshot(
            snapshot=store.get_snapshot(),
            event_recorded_at="2026-03-15T00:00:05Z",
        )
        self.assertIsNotNone(result)
        self.assertEqual(len(history.snapshots), initial_count + 1)

    def test_beyond_interval_writes(self):
        tempdir, history, store, controller = self._make(interval=5.0)
        self.addCleanup(tempdir.cleanup)

        controller.start_run(test_name="t", mode="live")
        initial_count = len(history.snapshots)

        result = controller.maybe_write_periodic_snapshot(
            snapshot=store.get_snapshot(),
            event_recorded_at="2026-03-15T00:00:07Z",
        )
        self.assertIsNotNone(result)
        self.assertEqual(len(history.snapshots), initial_count + 1)

    def test_negative_delta_does_not_write(self):
        """An event with a timestamp BEFORE the last snapshot must not
        trigger a new snapshot (out-of-order / older event)."""
        tempdir, history, store, controller = self._make(interval=5.0)
        self.addCleanup(tempdir.cleanup)

        controller.start_run(test_name="t", mode="live")

        # First: write a periodic snapshot at T+6
        controller.maybe_write_periodic_snapshot(
            snapshot=store.get_snapshot(),
            event_recorded_at="2026-03-15T00:00:06Z",
        )
        count_after_first = len(history.snapshots)

        # Second: event at T+4 (before the T+6 snapshot) — should NOT write
        result = controller.maybe_write_periodic_snapshot(
            snapshot=store.get_snapshot(),
            event_recorded_at="2026-03-15T00:00:04Z",
        )
        self.assertIsNone(result)
        self.assertEqual(len(history.snapshots), count_after_first)

    def test_periodic_snapshot_payload_has_recorded_at(self):
        tempdir, history, store, controller = self._make(interval=5.0)
        self.addCleanup(tempdir.cleanup)

        controller.start_run(test_name="t", mode="live")

        controller.maybe_write_periodic_snapshot(
            snapshot=store.get_snapshot(),
            event_recorded_at="2026-03-15T00:00:05Z",
        )
        # The periodic snapshot (second snapshot overall, after the initial one)
        _index, payload, _path = history.snapshots[-1]
        self.assertEqual(payload["recorded_at"], "2026-03-15T00:00:05Z")

    def test_not_running_returns_none(self):
        tempdir, history, store, controller = self._make()
        self.addCleanup(tempdir.cleanup)

        # Don't call start_run — history_manager.is_running is False
        result = controller.maybe_write_periodic_snapshot(
            snapshot=store.get_snapshot(),
            event_recorded_at="2026-03-15T00:00:05Z",
        )
        self.assertIsNone(result)
