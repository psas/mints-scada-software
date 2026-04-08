"""Test that periodic playback snapshots are triggered by operator_action
and command_out events, not only by telemetry.

This ensures runs recorded without CAN hardware (no telemetry_in events)
still produce intermediate snapshots for fast mid-run playback seek.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_unittest_dev.helpers.fakes import FakeHistoryManager
from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip

state_store_module = import_module_or_skip("backend.state_store")
run_controller_module = import_module_or_skip("backend.run_controller")
service_module = import_module_or_skip("backend.service")

StateStore = state_store_module.StateStore
RunController = run_controller_module.RunController


# FakeHistoryManager hardcodes started_wall_time to this value.
# All test event timestamps must be AFTER this baseline so that
# RunController.maybe_write_periodic_snapshot computes positive deltas.
_FAKE_RUN_START = "2026-03-15T00:00:00Z"


def _make_controller(
    *,
    snapshot_interval: float = 5.0,
) -> tuple[TemporaryDirectory, FakeHistoryManager, StateStore, RunController]:
    tmpdir = TemporaryDirectory()
    history = FakeHistoryManager(snapshot_dir=Path(tmpdir.name) / "snapshots")
    store = StateStore(
        service_name="backend_service",
        backend_started_at=_FAKE_RUN_START,
    )
    controller = RunController(history_manager=history, state_store=store)
    controller._periodic_snapshot_interval_seconds = snapshot_interval
    return tmpdir, history, store, controller


class TestPeriodicSnapshotFromOperatorAction(unittest.TestCase):
    """maybe_write_periodic_snapshot, when called with operator_action
    timestamps spaced > 5s apart, writes intermediate snapshots."""

    def test_operator_actions_spaced_apart_produce_snapshots(self):
        tmpdir, history, store, controller = _make_controller()
        self.addCleanup(tmpdir.cleanup)

        controller.start_run(test_name="no-telemetry", mode="live")
        initial_snapshot_count = len(history.snapshots)
        self.assertEqual(initial_snapshot_count, 1, "start_run writes snapshot 0")

        # Simulate operator actions at T+1s, T+6.5s, T+8s, T+12s.
        # Only T+6.5s and T+12s should trigger periodic snapshots because
        # the initial snapshot at start_run anchors _last_periodic_snapshot_recorded_at
        # to the run start time, and the 5-second interval gates the rest.
        timestamps = [
            "2026-03-15T00:00:01.000Z",  # T+1s — too close to start (< 5s)
            "2026-03-15T00:00:06.500Z",  # T+6.5s — > 5s since start
            "2026-03-15T00:00:08.000Z",  # T+8s — < 5s since T+6.5s
            "2026-03-15T00:00:12.000Z",  # T+12s — > 5s since T+6.5s
        ]

        for ts in timestamps:
            snapshot = store.get_snapshot()
            controller.maybe_write_periodic_snapshot(
                snapshot=snapshot,
                event_recorded_at=ts,
            )

        # initial (start_run) + 2 periodic (T+6.5s, T+12s)
        self.assertEqual(len(history.snapshots), 3)

    def test_no_snapshot_when_events_too_close(self):
        tmpdir, history, store, controller = _make_controller()
        self.addCleanup(tmpdir.cleanup)

        controller.start_run(test_name="rapid-fire", mode="live")
        initial_count = len(history.snapshots)

        # All events within 2 seconds of run start — none should trigger
        for i in range(5):
            ms = i * 400
            ts = f"2026-03-15T00:00:00.{ms:03d}Z"
            controller.maybe_write_periodic_snapshot(
                snapshot=store.get_snapshot(),
                event_recorded_at=ts,
            )

        self.assertEqual(len(history.snapshots), initial_count,
                         "No periodic snapshot when all events are < 5s apart")


class TestPeriodicSnapshotFromCommandOut(unittest.TestCase):
    """Same behavior for command_out event timestamps."""

    def test_command_events_spaced_apart_produce_snapshots(self):
        tmpdir, history, store, controller = _make_controller()
        self.addCleanup(tmpdir.cleanup)

        controller.start_run(test_name="commands-only", mode="live")
        initial_count = len(history.snapshots)

        # Two events at T+7s and T+14s — both > 5s from preceding snapshot
        for ts in ["2026-03-15T00:00:07.000Z", "2026-03-15T00:00:14.000Z"]:
            controller.maybe_write_periodic_snapshot(
                snapshot=store.get_snapshot(),
                event_recorded_at=ts,
            )

        self.assertEqual(len(history.snapshots), initial_count + 2)


class TestServiceHelperCallsSites(unittest.TestCase):
    """Verify BackendService._maybe_write_periodic_snapshot is called
    from operator_action and command_out recording paths."""

    def test_record_operator_action_calls_snapshot_helper(self):
        """_record_operator_action_if_running must attempt a periodic snapshot."""
        svc = self._make_minimal_service()
        svc.history_manager.is_running = True

        with patch.object(svc, "_maybe_write_periodic_snapshot") as mock_snap:
            svc._record_operator_action_if_running({
                "event_kind": "operator_action",
                "action": "hold_pressed",
                "recorded_at": "2026-03-15T00:00:10.000Z",
            })

        mock_snap.assert_called_once()
        call_arg = mock_snap.call_args[0][0]
        self.assertEqual(call_arg["action"], "hold_pressed")

    def test_record_command_out_calls_snapshot_helper(self):
        """_record_command_out_if_running must attempt a periodic snapshot."""
        svc = self._make_minimal_service()
        svc.history_manager.is_running = True

        with patch.object(svc, "_maybe_write_periodic_snapshot") as mock_snap:
            svc._record_command_out_if_running(
                {
                    "command_name": "open",
                    "device_id": "lox-xv-26",
                    "recorded_at": "2026-03-15T00:00:10.000Z",
                },
                result_summary={"ok": True},
            )

        mock_snap.assert_called_once()
        call_arg = mock_snap.call_args[0][0]
        self.assertEqual(call_arg["event_kind"], "command_out")

    def test_record_operator_action_no_snapshot_when_not_recording(self):
        """No snapshot attempt when history_manager is not running."""
        svc = self._make_minimal_service()
        svc.history_manager.is_running = False

        with patch.object(svc, "_maybe_write_periodic_snapshot") as mock_snap:
            svc._record_operator_action_if_running({
                "event_kind": "operator_action",
                "action": "test",
            })

        mock_snap.assert_not_called()

    def test_record_command_out_no_snapshot_when_not_recording(self):
        """No snapshot attempt when history_manager is not running."""
        svc = self._make_minimal_service()
        svc.history_manager.is_running = False

        with patch.object(svc, "_maybe_write_periodic_snapshot") as mock_snap:
            svc._record_command_out_if_running(
                {"command_name": "close", "device_id": "lox-xv-26"},
            )

        mock_snap.assert_not_called()

    def test_helper_swallows_exception(self):
        """_maybe_write_periodic_snapshot must not propagate exceptions."""
        svc = self._make_minimal_service()

        with patch.object(
            svc.run_controller,
            "maybe_write_periodic_snapshot",
            side_effect=RuntimeError("disk full"),
        ):
            # Should not raise
            svc._maybe_write_periodic_snapshot({"recorded_at": "2026-03-15T00:00:00Z"})

    @staticmethod
    def _make_minimal_service():
        """Build a BackendService with just enough wiring for the recording methods."""
        tmpdir_obj = TemporaryDirectory()
        tmpdir = tmpdir_obj.name
        history = FakeHistoryManager(snapshot_dir=Path(tmpdir) / "snapshots")
        store = StateStore(
            service_name="backend_service",
            backend_started_at="2026-03-15T00:00:00Z",
        )
        controller = RunController(history_manager=history, state_store=store)

        # Build a minimal service with just the attributes the recording
        # methods access.  We avoid full BackendService.__init__ because it
        # requires bus/device/ipc setup that isn't relevant here.
        svc = object.__new__(service_module.BackendService)
        svc.history_manager = history
        svc.state_store = store
        svc.run_controller = controller
        return svc


if __name__ == "__main__":
    unittest.main()
