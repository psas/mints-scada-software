# backend/structured_builder.py

from __future__ import annotations

from typing import Any, Mapping

from historymanager.manager import isoformat_z

from .telemetry_models import NormalizedTelemetryPacket

_SHARED_EVENT_IDENTITY_FIELDS = (
    "run_id",
    "stream",
    "recorded_at",
    "event_uid",
    "stream_seq",
    "canonical_hash",
)



def _copy_shared_event_identity(first_order_event: Mapping[str, Any] | None) -> dict[str, Any]:
    if first_order_event is None:
        return {}

    copied: dict[str, Any] = {}
    for field_name in _SHARED_EVENT_IDENTITY_FIELDS:
        value = first_order_event.get(field_name)
        if value is not None:
            copied[field_name] = value
    return copied


class StructuredEventBuilder:
    """Build raw first-order telemetry events and replay-oriented structured events."""

    def build_raw_telemetry_event(
        self,
        *,
        telemetry: NormalizedTelemetryPacket | None = None,
        meta: dict[str, Any] | None = None,
        packet: Any | None = None,
        runtime: Any | None = None,
        source: str = "bus",
    ) -> dict[str, Any]:
        if telemetry is None:
            if meta is None or packet is None:
                raise ValueError("telemetry or meta+packet must be provided")
            telemetry = NormalizedTelemetryPacket.from_meta_runtime_packet(
                meta=meta,
                runtime=runtime,
                packet=packet,
                source=source,
            )

        return telemetry.to_raw_event_payload()

    def build_structured_telemetry_event(
        self,
        *,
        telemetry: NormalizedTelemetryPacket | None = None,
        reduction: dict[str, Any],
        first_order_event: Mapping[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
        packet: Any | None = None,
        runtime: Any | None = None,
        source: str = "bus",
    ) -> dict[str, Any]:
        if telemetry is None:
            if meta is None or packet is None:
                raise ValueError("telemetry or meta+packet must be provided")
            telemetry = NormalizedTelemetryPacket.from_meta_runtime_packet(
                meta=meta,
                runtime=runtime,
                packet=packet,
                source=source,
            )

        semantic = reduction.get("semantic")
        if not isinstance(semantic, Mapping):
            semantic = {
                "domain": "generic",
                "summary": "No semantic decode available",
                "fields": {},
            }

        payload = {
            **_copy_shared_event_identity(first_order_event),
            "event_kind": "telemetry_in",
            "observed_at": telemetry.wall_time,
            "structured_at": isoformat_z(),
            "device_id": telemetry.device_id,
            "device_name": telemetry.device_name,
            "device_type": telemetry.device_type,
            "device_group": telemetry.device_group,
            "device_systems": list(telemetry.device_systems),
            "widget_type": telemetry.widget_type,
            "bus_address": telemetry.bus_address,
            "source": telemetry.source,
            "packet": telemetry.packet_summary(),
            "runtime": telemetry.runtime_summary(),
            "semantic": {
                "domain": semantic.get("domain"),
                "summary": semantic.get("summary"),
                "fields": dict(semantic.get("fields", {})),
            },
        }

        semantic_fields = semantic.get("fields", {})
        if isinstance(semantic_fields, Mapping):
            domain = semantic.get("domain")
            if domain == "pressure":
                payload["pressure"] = semantic_fields.get("pressure")
                payload["pressure_units"] = semantic_fields.get("units")
            elif domain == "temperature":
                payload["temperature"] = semantic_fields.get("temperature")
                payload["temperature_units"] = semantic_fields.get("units")
            elif domain == "valve":
                payload["valve_state"] = semantic_fields.get("state")
                payload["valve_position"] = semantic_fields.get("position")
            elif domain == "flow":
                payload["flow"] = semantic_fields.get("flow")
                payload["flow_units"] = semantic_fields.get("units")
            elif domain == "load":
                payload["load"] = semantic_fields.get("load")
                payload["load_units"] = semantic_fields.get("units")

        return payload
