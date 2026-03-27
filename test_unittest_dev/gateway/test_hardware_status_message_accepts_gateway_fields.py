from __future__ import annotations

import unittest

from test_unittest_dev.helpers.repo_test_tools import import_module_or_skip

ipc_models = import_module_or_skip("gateway.ipc_models")
hardware_status_message = ipc_models.hardware_status_message


class TestHardwareStatusMessageAcceptsGatewayFields(unittest.TestCase):
    def test_accepts_extended_gateway_fields(self):
        message = hardware_status_message(
            connected=True,
            reconnecting=False,
            status="connected",
            reason="gateway_initialize_live_hardware",
            sender="test-sender",
            bitrate=125000,
            registered_ids=["ig-xv-24"],
            skipped_ids=["ig-xv-27"],
            registered_count=1,
            skipped_count=1,
            already_running=False,
            packet_listener_attached=True,
            wall_time="2026-03-26T22:00:00Z",
        )

        self.assertEqual(message.type, "hardware_status")
        self.assertEqual(message.payload["connected"], True)
        self.assertEqual(message.payload["reconnecting"], False)
        self.assertEqual(message.payload["status"], "connected")
        self.assertEqual(message.payload["reason"], "gateway_initialize_live_hardware")
        self.assertEqual(message.payload["sender"], "test-sender")
        self.assertEqual(message.payload["bitrate"], 125000)
        self.assertEqual(message.payload["registered_ids"], ["ig-xv-24"])
        self.assertEqual(message.payload["skipped_ids"], ["ig-xv-27"])
        self.assertEqual(message.payload["registered_count"], 1)
        self.assertEqual(message.payload["skipped_count"], 1)
        self.assertEqual(message.payload["already_running"], False)
        self.assertEqual(message.payload["packet_listener_attached"], True)
        self.assertEqual(message.payload["wall_time"], "2026-03-26T22:00:00Z")

    def test_old_minimal_call_still_works(self):
        message = hardware_status_message(
            connected=False,
            sender="test-sender",
            bitrate=250000,
            registered_ids=[],
            skipped_ids=["ig-xv-24"],
        )

        self.assertEqual(message.type, "hardware_status")
        self.assertEqual(message.payload["connected"], False)
        self.assertEqual(message.payload["reconnecting"], False)
        self.assertEqual(message.payload["status"], "disconnected")
        self.assertEqual(message.payload["sender"], "test-sender")
        self.assertEqual(message.payload["bitrate"], 250000)
        self.assertEqual(message.payload["registered_ids"], [])
        self.assertEqual(message.payload["skipped_ids"], ["ig-xv-24"])
        self.assertEqual(message.payload["registered_count"], 0)
        self.assertEqual(message.payload["skipped_count"], 1)