from __future__ import annotations

import unittest

from gui.graph_data import (
    GraphChannelDescriptor,
    GraphSample,
    GraphWindow,
    build_channel_key,
    split_channel_key,
)


class TestGraphData(unittest.TestCase):
    def test_graph_sample_normalizes_fields(self):
        sample = GraphSample(
            timestamp=123,
            channel_key="lc-1.pressure",
            value=456,
            source="live",
            display_name="LC-1 Pressure",
            unit="psi",
        )

        self.assertEqual(sample.timestamp, 123.0)
        self.assertEqual(sample.value, 456.0)
        self.assertEqual(sample.label, "LC-1 Pressure")

    def test_graph_sample_rejects_empty_channel(self):
        with self.assertRaises(ValueError):
            GraphSample(timestamp=1.0, channel_key="", value=2.0)

    def test_graph_window_rejects_inverted_range(self):
        with self.assertRaises(ValueError):
            GraphWindow(start_ts=10.0, end_ts=9.0)

    def test_channel_descriptor_uses_channel_as_fallback_label(self):
        descriptor = GraphChannelDescriptor(channel_key="pt-1.value")
        self.assertEqual(descriptor.label, "pt-1.value")

    def test_build_and_split_channel_key(self):
        key = build_channel_key("pt-1", "value")
        self.assertEqual(key, "pt-1.value")
        self.assertEqual(split_channel_key(key), ("pt-1", "value"))
        self.assertEqual(split_channel_key("ig-xv-24"), ("ig-xv-24", None))


if __name__ == "__main__":
    unittest.main()
