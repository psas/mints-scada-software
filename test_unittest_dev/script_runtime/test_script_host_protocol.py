from __future__ import annotations

import unittest

from scripts.script_runtime.script_protocol import (
    SCRIPT_HOST_MESSAGE_PING,
    build_message,
    decode_json_line,
)


class ScriptHostProtocolTests(unittest.TestCase):
    def test_protocol_round_trip_preserves_request_id(self) -> None:
        payload = build_message(
            SCRIPT_HOST_MESSAGE_PING,
            {"value": 1},
            request_id="abc123",
        )
        decoded = decode_json_line(__import__("json").dumps(payload))
        self.assertEqual(decoded["type"], SCRIPT_HOST_MESSAGE_PING)
        self.assertEqual(decoded["payload"]["value"], 1)
        self.assertEqual(decoded["request_id"], "abc123")


if __name__ == "__main__":
    unittest.main()
