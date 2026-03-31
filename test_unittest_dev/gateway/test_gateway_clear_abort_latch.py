from __future__ import annotations

import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gateway.service import GatewayService
from gateway.ipc_models import GatewayIPCMessage
from scripts.script_runtime.abort_flow_contract import CLEAR_ABORT_LATCH_RELAY_MESSAGE_TYPE
from scripts.script_runtime.script_contract import ABORT_RELAY_MESSAGE_TYPE


from gateway.backend_client import BackendIPCClient


class _DummyBackendClient:
    def __init__(self) -> None:
        self.abort_forward_calls = 0
        self.clear_forward_calls = 0

    def forward_abort_to_backend(self, *, operator_action_payload, command_payload):
        self.abort_forward_calls += 1
        return True, None

    def forward_clear_abort_latch_to_backend(self, *, operator_action_payload, command_payload):
        self.clear_forward_calls += 1
        return True, None

    def close(self):
        return None

    def gateway_hardware_status(self, payload):
        return []


class GatewayClearAbortLatchTests(unittest.TestCase):
    def test_abort_latch_can_be_cleared(self) -> None:
        service = GatewayService(project_root=PROJECT_ROOT)
        service.backend_client = _DummyBackendClient()

        abort_reply = list(
            service.handle_message(
                "client",
                GatewayIPCMessage(
                    type=ABORT_RELAY_MESSAGE_TYPE,
                    payload={
                        "relay_request_id": "r1",
                        "relay_session_id": "s1",
                        "operator_action": {"action": "abort_pressed"},
                        "command_payload": {"command_name": "abort"},
                    },
                ),
            )
        )
        self.assertTrue(service._abort_latched)
        self.assertEqual(abort_reply[0].type, "abort_result")

        clear_reply = list(
            service.handle_message(
                "client",
                GatewayIPCMessage(
                    type=CLEAR_ABORT_LATCH_RELAY_MESSAGE_TYPE,
                    payload={
                        "relay_request_id": "r2",
                        "relay_session_id": "s1",
                        "operator_action": {"action": "clear_abort_latch_requested"},
                        "command_payload": {"command_name": "clear_abort_latch"},
                    },
                ),
            )
        )
        self.assertFalse(service._abort_latched)
        self.assertEqual(clear_reply[0].type, "clear_abort_latch_result")
        self.assertTrue(clear_reply[0].payload["was_latched"])
        self.assertEqual(service.backend_client.clear_forward_calls, 1)


class BackendClientMethodTests(unittest.TestCase):
    """Verify forward_clear_abort_latch_to_backend is a real class method."""

    def test_forward_clear_abort_latch_is_class_method(self) -> None:
        self.assertTrue(
            hasattr(BackendIPCClient, "forward_clear_abort_latch_to_backend"),
            "forward_clear_abort_latch_to_backend must be a method of BackendIPCClient",
        )
        import inspect
        self.assertTrue(
            callable(getattr(BackendIPCClient, "forward_clear_abort_latch_to_backend")),
        )
        sig = inspect.signature(BackendIPCClient.forward_clear_abort_latch_to_backend)
        self.assertIn("self", sig.parameters)


if __name__ == "__main__":
    unittest.main()
