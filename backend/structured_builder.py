from __future__ import annotations

from typing import Any, Mapping

from historymanager.manager import isoformat_z

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
        meta: dict[str, Any],
        packet: Any,
        source: str = "bus",
    ) -> dict[str, Any]:
        return {
            "event_kind": "telemetry_packet",
            "source": source,
            "device_id": meta["id"],
            "device_name": meta["name"],
            "device_type": meta["deviceType"],
            "device_group": meta["deviceGroup"],
            "device_systems": list(meta["deviceSystems"]),
            "bus_address": meta["address"],
            "packet": {
                "id": packet.id,
                "seq": packet.seq,
                "cmd": packet.cmd,
                "reply": bool(packet.reply),
                "err": bool(packet.err),
                "rsvd": bool(packet.rsvd),
                "timestamp": getattr(packet, "timestamp", None),
                "data": list(packet.data),
                "data_hex": " ".join(f"{b:02X}" for b in packet.data),
            },
        }

    def build_structured_telemetry_event(
        self,
        *,
        meta: dict[str, Any],
        reduction: dict[str, Any],
        first_order_event: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            **_copy_shared_event_identity(first_order_event),
            "event_kind": "telemetry_in",
            "structured_at": isoformat_z(),
            "device_id": meta["id"],
            "device_name": meta["name"],
            "device_type": meta["deviceType"],
            "device_group": meta["deviceGroup"],
            "device_systems": list(meta["deviceSystems"]),
            "widget_type": meta["widgetType"],
            "bus_address": meta["address"],
            "source": reduction["source"],
            "packet": dict(reduction["packet_summary"]),
            "runtime": {
                "value": reduction.get("runtime_value"),
                "aux": reduction.get("runtime_aux"),
                "time": reduction.get("runtime_time"),
            },
        }