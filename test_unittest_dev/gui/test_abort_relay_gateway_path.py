from __future__ import annotations

import unittest

from gui.abort_relay import AbortRelayServer


class AbortRelayGatewayPathTests(unittest.TestCase):
    def test_abort_relay_routes_abort_to_gateway_exchange(self) -> None:
        server = AbortRelayServer(
            relay_socket="/tmp/test-abort-relay.sock",
            gateway_socket="/tmp/test-gateway.sock",
        )
        captured: dict[str, object] = {}

        def fake_gateway_exchange(*, payload, expected_response_types, timeout_s=3.0):
            captured["payload"] = dict(payload)
            captured["expected_response_types"] = tuple(expected_response_types)
            return {
                "type": "abort_result",
                "payload": {
                    "ok": True,
                    "abort_latched": True,
                    "backend_forwarded": True,
                },
            }

        server._gateway_exchange = fake_gateway_exchange  # type: ignore[method-assign]

        response = server._handle_abort_request(
            {
                "source_window_role": "controller",
                "source_window_kind": "controller",
                "source_mode": "live",
            }
        )

        self.assertEqual(response["type"], "abort_result")
        self.assertTrue(response["payload"]["ok"])
        sent = captured["payload"]
        self.assertEqual(sent["requested_via"], "abort_relay")
        self.assertIn("operator_action", sent)
        self.assertIn("command_payload", sent)
        self.assertEqual(captured["expected_response_types"], ("abort_result", "error"))


if __name__ == "__main__":
    unittest.main()
