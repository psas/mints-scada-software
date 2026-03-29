from __future__ import annotations

import unittest

from gui.graph_data import GraphChannelDescriptor, GraphSample
from gui.graph_provider import InMemoryGraphDataProvider


class TestInMemoryGraphDataProvider(unittest.TestCase):
    def test_register_and_list_descriptors(self):
        provider = InMemoryGraphDataProvider()
        provider.register_channels(
            [
                GraphChannelDescriptor(channel_key="b.value", display_name="B"),
                GraphChannelDescriptor(channel_key="a.value", display_name="A"),
            ]
        )

        descriptors = provider.get_channel_descriptors()
        self.assertEqual([row.channel_key for row in descriptors], ["a.value", "b.value"])

    def test_ingest_samples_respects_subscriptions(self):
        provider = InMemoryGraphDataProvider()
        seen: list[list[GraphSample]] = []
        provider.add_listener(lambda samples: seen.append(list(samples)))
        provider.subscribe(["pt-1.value"])

        emitted = provider.ingest_samples(
            [
                GraphSample(timestamp=1.0, channel_key="pt-1.value", value=10.0, source="live"),
                GraphSample(timestamp=1.0, channel_key="pt-2.value", value=20.0, source="live"),
            ]
        )

        self.assertEqual([row.channel_key for row in emitted], ["pt-1.value"])
        self.assertEqual(len(seen), 1)
        self.assertEqual([row.channel_key for row in seen[0]], ["pt-1.value"])

    def test_get_samples_uses_provider_window_when_explicit_range_missing(self):
        provider = InMemoryGraphDataProvider()
        provider.ingest_samples(
            [
                GraphSample(timestamp=1.0, channel_key="pt-1.value", value=10.0),
                GraphSample(timestamp=5.0, channel_key="pt-1.value", value=20.0),
                GraphSample(timestamp=9.0, channel_key="pt-1.value", value=30.0),
            ]
        )
        provider.set_time_window(start_ts=4.0, end_ts=8.0)

        rows = provider.get_samples(channel_keys=["pt-1.value"])
        self.assertEqual([row.value for row in rows], [20.0])

    def test_retention_trims_old_rows(self):
        provider = InMemoryGraphDataProvider(retention_seconds=5.0)
        provider.ingest_samples(
            [
                GraphSample(timestamp=1.0, channel_key="pt-1.value", value=10.0),
                GraphSample(timestamp=3.0, channel_key="pt-1.value", value=20.0),
                GraphSample(timestamp=9.5, channel_key="pt-1.value", value=30.0),
            ]
        )

        rows = provider.get_samples(channel_keys=["pt-1.value"])
        self.assertEqual([row.value for row in rows], [30.0])

    def test_samples_are_returned_sorted(self):
        provider = InMemoryGraphDataProvider()
        provider.ingest_samples(
            [
                GraphSample(timestamp=5.0, channel_key="pt-1.value", value=50.0),
                GraphSample(timestamp=1.0, channel_key="pt-1.value", value=10.0),
                GraphSample(timestamp=3.0, channel_key="pt-1.value", value=30.0),
            ]
        )
        rows = provider.get_samples(channel_keys=["pt-1.value"])
        self.assertEqual([row.timestamp for row in rows], [1.0, 3.0, 5.0])


if __name__ == "__main__":
    unittest.main()
