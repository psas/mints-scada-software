import unittest

from historymanager.integrity import (
    RAW_STREAM_FILES,
    SHARED_STREAM_NAMES as INTEGRITY_SHARED_STREAM_NAMES,
    STRUCTURED_STREAM_FILES,
)
from historymanager.models import (
    FIRST_ORDER_EVENT_STREAMS,
    RAW_STREAM_FILENAMES,
    SHARED_STREAM_NAMES,
    STRUCTURED_STREAM_FILENAMES,
)
from historymanager.rebuild import _PASS_THROUGH_STREAMS


class TestHistoryStreamSplit(unittest.TestCase):
    def test_raw_streams_use_wire_command_out(self):
        self.assertIn("wire_command_out", RAW_STREAM_FILENAMES)
        self.assertNotIn("command_out", RAW_STREAM_FILENAMES)
        self.assertEqual(
            RAW_STREAM_FILENAMES["wire_command_out"],
            "wire_command_out.raw.jsonl",
        )

    def test_structured_streams_keep_semantic_command_out(self):
        self.assertIn("command_out", STRUCTURED_STREAM_FILENAMES)
        self.assertNotIn("wire_command_out", STRUCTURED_STREAM_FILENAMES)
        self.assertEqual(
            STRUCTURED_STREAM_FILENAMES["command_out"],
            "command_out.jsonl",
        )

    def test_model_shared_streams_exclude_command_stream_split(self):
        self.assertIn("telemetry_in", SHARED_STREAM_NAMES)
        self.assertIn("operator_action", SHARED_STREAM_NAMES)
        self.assertIn("system_event", SHARED_STREAM_NAMES)
        self.assertNotIn("wire_command_out", SHARED_STREAM_NAMES)
        self.assertNotIn("command_out", SHARED_STREAM_NAMES)

    def test_integrity_shared_streams_exclude_command_stream_split(self):
        self.assertIn("telemetry_in", INTEGRITY_SHARED_STREAM_NAMES)
        self.assertIn("operator_action", INTEGRITY_SHARED_STREAM_NAMES)
        self.assertIn("system_event", INTEGRITY_SHARED_STREAM_NAMES)
        self.assertNotIn("wire_command_out", INTEGRITY_SHARED_STREAM_NAMES)
        self.assertNotIn("command_out", INTEGRITY_SHARED_STREAM_NAMES)

    def test_first_order_streams_cover_both_raw_and_structured_sets(self):
        expected = {
            "telemetry_in",
            "wire_command_out",
            "command_out",
            "operator_action",
            "system_event",
        }
        self.assertEqual(set(FIRST_ORDER_EVENT_STREAMS), expected)

    def test_integrity_stream_maps_match_intended_split(self):
        self.assertEqual(
            set(RAW_STREAM_FILES.keys()),
            {"telemetry_in", "wire_command_out", "operator_action", "system_event"},
        )
        self.assertEqual(
            set(STRUCTURED_STREAM_FILES.keys()),
            {"telemetry_in", "command_out", "operator_action", "system_event"},
        )

    def test_rebuild_pass_through_streams_do_not_include_command_streams(self):
        self.assertIn("operator_action", _PASS_THROUGH_STREAMS)
        self.assertIn("system_event", _PASS_THROUGH_STREAMS)
        self.assertNotIn("wire_command_out", _PASS_THROUGH_STREAMS)
        self.assertNotIn("command_out", _PASS_THROUGH_STREAMS)