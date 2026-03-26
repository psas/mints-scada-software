import unittest

from backend.service import BackendService


class TestTelemetryIdentityHelpers(unittest.TestCase):
    def test_extract_raw_identity_fields_only_returns_identity_keys(self):
        service = BackendService.__new__(BackendService)

        raw_event = {
            "run_id": "run-123",
            "recorded_at": "2026-03-26T12:00:00Z",
            "stream": "telemetry_in",
            "stream_seq": 17,
            "event_uid": "run-123:telemetry_in:00000017",
            "canonical_hash": "abc123",
            "device_id": "PT-1",
            "data": [1, 2, 3, 4, 5, 6],
        }

        identity = service._extract_raw_identity_fields(raw_event)

        self.assertEqual(
            identity,
            {
                "run_id": "run-123",
                "recorded_at": "2026-03-26T12:00:00Z",
                "stream": "telemetry_in",
                "stream_seq": 17,
                "event_uid": "run-123:telemetry_in:00000017",
                "canonical_hash": "abc123",
            },
        )

    def test_apply_raw_identity_to_structured_event_overrides_only_identity_fields(self):
        service = BackendService.__new__(BackendService)

        structured_event = {
            "event_kind": "telemetry_in",
            "device_id": "PT-1",
            "pressure_psi": 420,
            "stream_seq": 999,
            "event_uid": "old",
            "canonical_hash": "oldhash",
        }
        raw_identity = {
            "run_id": "run-9",
            "recorded_at": "2026-03-26T12:34:56Z",
            "stream": "telemetry_in",
            "stream_seq": 4,
            "event_uid": "run-9:telemetry_in:00000004",
            "canonical_hash": "newhash",
        }

        merged = service._apply_raw_identity_to_structured_event(
            structured_event,
            raw_identity,
        )

        self.assertEqual(merged["run_id"], "run-9")
        self.assertEqual(merged["recorded_at"], "2026-03-26T12:34:56Z")
        self.assertEqual(merged["stream"], "telemetry_in")
        self.assertEqual(merged["stream_seq"], 4)
        self.assertEqual(merged["event_uid"], "run-9:telemetry_in:00000004")
        self.assertEqual(merged["canonical_hash"], "newhash")

        # Non-identity structured fields should remain untouched.
        self.assertEqual(merged["event_kind"], "telemetry_in")
        self.assertEqual(merged["device_id"], "PT-1")
        self.assertEqual(merged["pressure_psi"], 420)