from __future__ import annotations

import unittest
from unittest import mock

from gui.abort_relay import AbortRelayServer, send_clear_abort_latch_request
from scripts.script_runtime.script_contract import ABORT_RELAY_MESSAGE_TYPE


class AbortRelayClearLatchTests(unittest.TestCase):
    def test_send_clear_abort_latch_request_uses_canonical_message_type(self) -> None:
        with mock.patch(
            "gui.abort_relay.send_abort_relay_message",
            return_value={"type": "clear_abort_latch_result", "payload": {"ok": True}},
        ) as mocked:
            reply = send_clear_abort_latch_request(
                relay_socket="/tmp/test.sock",
                source_window_role="live_scada",
                source_window_kind="scada",
                source_mode="live",
            )
        self.assertEqual(reply["type"], "clear_abort_latch_result")
        self.assertEqual(mocked.call_args.kwargs["message_type"], "clear_abort_latch_request")


class AbortRelayServerAbortMessageTypeTests(unittest.TestCase):
    """Verify _handle_abort_request passes message_type to _gateway_exchange."""

    def test_handle_abort_request_passes_message_type(self) -> None:
        server = AbortRelayServer(
            relay_socket="/tmp/relay_test.sock",
            gateway_socket="/tmp/gateway_test.sock",
        )
        captured_kwargs = {}

        def fake_gateway_exchange(**kwargs):
            captured_kwargs.update(kwargs)
            return {
                "type": "abort_result",
                "payload": {"ok": True, "abort_latched": True},
            }

        server._gateway_exchange = fake_gateway_exchange

        result = server._handle_abort_request({
            "source_window_role": "controller",
            "source_window_kind": "controller",
            "source_mode": "live",
        })

        self.assertIn("message_type", captured_kwargs,
                       "_gateway_exchange must be called with message_type")
        self.assertEqual(captured_kwargs["message_type"], ABORT_RELAY_MESSAGE_TYPE)
        self.assertTrue(result["payload"]["ok"])


if __name__ == "__main__":
    unittest.main()
