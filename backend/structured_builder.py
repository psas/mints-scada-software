"""backend/structured_builder.py

Build first-order and structured telemetry event payloads.

This module converts normalized telemetry packets into the backend's raw
first-order telemetry event shape and the replay-oriented structured telemetry
shape used by downstream history, export, and playback paths.
"""

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


def _copy_shared_event_identity(
    first_order_event: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Copy shared archive identity fields from a first-order event.

    Args:
        first_order_event: First-order event whose shared identity fields should
            be mirrored into a structured event.

    Returns:
        A dictionary containing only the shared identity fields that are present
        and non-None in ``first_order_event``.
    """
    if first_order_event is None:
        return {}

    copied: dict[str, Any] = {}
    for field_name in _SHARED_EVENT_IDENTITY_FIELDS:
        value = first_order_event.get(field_name)
        if value is not None:
            copied[field_name] = value
    return copied


class StructuredEventBuilder:
    """Build raw telemetry events and replay-oriented structured telemetry events.

    The builder accepts either a pre-normalized ``NormalizedTelemetryPacket`` or
    the lower-level ``meta``/``runtime``/``packet`` inputs needed to construct
    one. Structured events preserve shared archive identity from the matching
    first-order event when that event is available.
    """

    def build_raw_telemetry_event(
        self,
        *,
        telemetry: NormalizedTelemetryPacket | None = None,
        meta: dict[str, Any] | None = None,
        packet: Any | None = None,
        runtime: Any | None = None,
        source: str = "bus",
    ) -> dict[str, Any]:
        """Build the raw first-order telemetry payload for a packet observation.

        Args:
            telemetry: Pre-normalized telemetry packet to serialize.
            meta: Device metadata used to normalize the packet when ``telemetry``
                is not provided.
            packet: Raw packet object used to normalize the event when
                ``telemetry`` is not provided.
            runtime: Runtime decode associated with ``packet``.
            source: Source label recorded on the normalized telemetry packet when
                it must be constructed here.

        Returns:
            The raw telemetry event payload produced by
            ``NormalizedTelemetryPacket.to_raw_event_payload()``.

        Raises:
            ValueError: If neither ``telemetry`` nor both ``meta`` and
                ``packet`` are provided.
        """
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
        """Build the structured telemetry payload used by replay-oriented history.

        The structured payload carries normalized packet and runtime summaries,
        reducer-provided semantic information, and selected convenience fields
        for known semantic domains such as pressure, temperature, valve, flow,
        and load. When a matching first-order event is provided, its shared
        archive identity fields are copied into the structured payload.

        Args:
            telemetry: Pre-normalized telemetry packet to serialize.
            reduction: Reducer output associated with the telemetry packet. The
                builder reads its ``semantic`` mapping when present.
            first_order_event: Matching first-order event whose shared identity
                fields should be preserved on the structured event.
            meta: Device metadata used to normalize the packet when ``telemetry``
                is not provided.
            packet: Raw packet object used to normalize the event when
                ``telemetry`` is not provided.
            runtime: Runtime decode associated with ``packet``.
            source: Source label recorded on the normalized telemetry packet when
                it must be constructed here.

            Returns:
                A structured telemetry payload containing shared archive identity,
                normalized device and packet metadata, reducer semantic data, and
                domain-specific convenience fields when available.

        Raises:
            ValueError: If neither ``telemetry`` nor both ``meta`` and
                ``packet`` are provided.
        """
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
