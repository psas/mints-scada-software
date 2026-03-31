from __future__ import annotations

import unittest
from types import SimpleNamespace

from gateway.ipc_models import GatewayIPCMessage
from gateway.service import GatewayService
from scripts.script_runtime.script_contract import ABORT_RELAY_MESSAGE_TYPE


class _StubBackendClient:
    def __init__(self, *, forwarded: bool = True, reason: str | None = None) -> None:
        self.forwarded = forwarded
        self.reason = reason
        self.calls: list[dict] = []

    def forward_abort_to_backend(self, *, operator_action_payload, command_payload):
        self.calls.append(
            {
                "operator_action_payload": dict(operator_action_payload),
                "command_payload": dict(command_payload),
            }
        )
        return self.forwarded, self.reason


class _StubRawHistoryManager:
    def __init__(self, *, is_running: bool = True) -> None:
        self.is_running = is_running
        self.current_run = None
        self.events: list[tuple[str, dict]] = []

    def record_raw_event(self, stream_name: str, event: dict) -> None:
        self.events.append((stream_name, dict(event)))


class GatewayAbortLatchTests(unittest.TestCase):
    def _make_service(self) -> GatewayService:
        service = GatewayService.__new__(GatewayService)
        service.service_name = "teststand-gateway"
        service.started_at = "2026-03-30T00:00:00Z"
        service.supported_messages = [ABORT_RELAY_MESSAGE_TYPE, "send_packet"]
        service._connected_clients = set()
        service._last_registered_ids = []
        service._last_skipped_ids = []
        service._bus_connected = True
        service._backend_link_ok = True
        service._last_backend_link_failure_reason = None
        service._abort_latched = False
        service._abort_latched_at = None
        service._abort_latched_request_id = None
        service._abort_latched_session_id = None
        service.raw_history_manager = _StubRawHistoryManager(is_running=True)
        service.backend_client = _StubBackendClient(forwarded=True, reason=None)
        service.bus_manager = SimpleNamespace(sender="test", bitrate=1)
        return service

    def test_abort_request_latches_gateway_and_forwards_backend(self) -> None:
        service = self._make_service()
        payload = {
            "relay_request_id": "req-1",
            "relay_session_id": "sess-1",
            "requested_via": "abort_relay",
            "source_window_role": "controller",
            "operator_action": {"action": "abort_pressed"},
            "command_payload": {"command_name": "abort"},
        }

        response = service._handle_abort_request_message(payload)

        self.assertEqual(response.type, "abort_result")
        self.assertTrue(response.payload["ok"])
        self.assertTrue(response.payload["abort_latched"])
        self.assertTrue(service._abort_latched)
        self.assertEqual(service._abort_latched_request_id, "req-1")
        self.assertEqual(len(service.backend_client.calls), 1)
        self.assertEqual(service.raw_history_manager.events[0][0], "system_event")

    def test_send_packet_is_rejected_after_abort_latch(self) -> None:
        service = self._make_service()
        service._abort_latched = True

        responses = list(
            service.handle_message(
                client_id="abc",
                message=GatewayIPCMessage(type="send_packet", payload={"id": 1}),
            )
        )

        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].type, "error")
        self.assertIn("abort latch is active", responses[0].payload["message"])


if __name__ == "__main__":
    unittest.main()
