# backend/telemetry_models.py

"""Telemetry normalization models used by the backend ingest path.

This module defines the immutable normalized telemetry packet shape that the
backend uses to combine device metadata, packet fields, and runtime adapter
state before reducing telemetry into backend state or recording raw events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from historymanager.manager import isoformat_z


def _copy_sequence_of_ints(value: Any) -> tuple[int, ...]:
    """Copy a packet-like byte sequence into an integer tuple.

    Args:
        value: Sequence value to normalize.

    Returns:
        A tuple of integers. Returns an empty tuple when ``value`` is None.
    """
    if value is None:
        return ()
    return tuple(int(item) for item in value)


def _copy_mapping(value: Any) -> Any:
    """Recursively copy nested mapping and sequence values.

    Mapping keys are coerced to strings. Lists and tuples are copied as new
    lists so nested runtime and metadata payloads can be detached from their
    source objects before being stored in the normalized packet.

    Args:
        value: Value to copy.

    Returns:
        A recursively copied value for mappings, lists, and tuples. Scalar
        values are returned unchanged.
    """
    if isinstance(value, Mapping):
        return {str(key): _copy_mapping(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_mapping(item) for item in value]
    if isinstance(value, tuple):
        return [_copy_mapping(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class NormalizedTelemetryPacket:
    """Immutable normalized view of a telemetry packet and runtime snapshot.

    Instances combine static device metadata, packet-level transport fields, and
    runtime adapter values into a backend-friendly structure that can be reduced
    into authoritative state or serialized into canonical raw telemetry events.
    """

    wall_time: str
    source: str
    device_id: str
    device_name: str
    device_type: str
    device_group: str
    device_systems: tuple[str, ...]
    widget_type: str | None
    bus_address: int | None
    meta: dict[str, Any] = field(default_factory=dict)

    packet_id: int = 0
    packet_seq: int = 0
    packet_cmd: int = 0
    packet_reply: bool = False
    packet_err: bool = False
    packet_rsvd: bool = False
    packet_timestamp: float | None = None
    packet_data: tuple[int, ...] = field(default_factory=tuple)
    packet_data_hex: str = ""

    runtime_value: Any = None
    runtime_aux: Any = None
    runtime_time: Any = None
    runtime_state: Any = None
    runtime_position: Any = None
    runtime_status: Any = None

    @classmethod
    def from_meta_runtime_packet(
        cls,
        *,
        meta: Mapping[str, Any],
        runtime: Any,
        packet: Any,
        source: str,
        wall_time: str | None = None,
    ) -> "NormalizedTelemetryPacket":
        """Build a normalized packet from device metadata, runtime data, and packet data.

        The method snapshots selected fields from the device metadata mapping,
        the runtime object, and the packet object into an immutable structure.
        Nested metadata and runtime values are copied so later mutations on the
        source objects do not affect the normalized packet.

        Args:
            meta: Device metadata mapping for the packet source. Expected to
                provide canonical device fields such as ``id``, ``name``,
                ``deviceType``, and ``deviceGroup``.
            runtime: Runtime adapter object that may expose ``value``, ``aux``,
                ``time``, ``state``, ``position``, and ``status`` attributes.
            packet: Data-packet-like object that may expose ``id``, ``seq``,
                ``cmd``, ``reply``, ``err``, ``rsvd``, ``timestamp``, and
                ``data`` attributes.
            source: Ingest source label to store on the normalized packet.
            wall_time: Wall-clock timestamp for the observation. Uses the
                current UTC timestamp when omitted.

        Returns:
            A normalized telemetry packet containing copied metadata, packet
            fields, and runtime summaries.
        """
        packet_data = _copy_sequence_of_ints(getattr(packet, "data", ()) or ())
        packet_data_hex = " ".join(f"{byte:02X}" for byte in packet_data)

        return cls(
            wall_time=wall_time or isoformat_z(),
            source=str(source),
            device_id=str(meta["id"]),
            device_name=str(meta["name"]),
            device_type=str(meta["deviceType"]),
            device_group=str(meta["deviceGroup"]),
            device_systems=tuple(
                str(item) for item in list(meta.get("deviceSystems", []))
            ),
            widget_type=(
                str(meta["widgetType"]) if meta.get("widgetType") is not None else None
            ),
            bus_address=(
                int(meta["address"]) if meta.get("address") is not None else None
            ),
            meta={str(key): _copy_mapping(value) for key, value in dict(meta).items()},
            packet_id=int(getattr(packet, "id", 0) or 0),
            packet_seq=int(getattr(packet, "seq", 0) or 0),
            packet_cmd=int(getattr(packet, "cmd", 0) or 0),
            packet_reply=bool(getattr(packet, "reply", False)),
            packet_err=bool(getattr(packet, "err", False)),
            packet_rsvd=bool(getattr(packet, "rsvd", False)),
            packet_timestamp=getattr(packet, "timestamp", None),
            packet_data=packet_data,
            packet_data_hex=packet_data_hex,
            runtime_value=_copy_mapping(getattr(runtime, "value", None)),
            runtime_aux=_copy_mapping(getattr(runtime, "aux", None)),
            runtime_time=_copy_mapping(getattr(runtime, "time", None)),
            runtime_state=_copy_mapping(getattr(runtime, "state", None)),
            runtime_position=_copy_mapping(getattr(runtime, "position", None)),
            runtime_status=_copy_mapping(getattr(runtime, "status", None)),
        )

    def packet_summary(self) -> dict[str, Any]:
        """Build the packet sub-payload used by raw telemetry events.

        Returns:
            A dictionary containing normalized packet transport fields and both
            integer-list and hex-string representations of packet data.
        """
        return {
            "id": self.packet_id,
            "seq": self.packet_seq,
            "cmd": self.packet_cmd,
            "reply": self.packet_reply,
            "err": self.packet_err,
            "rsvd": self.packet_rsvd,
            "timestamp": self.packet_timestamp,
            "data": list(self.packet_data),
            "data_hex": self.packet_data_hex,
        }

    def runtime_summary(self) -> dict[str, Any]:
        """Build the runtime sub-payload used by raw telemetry events.

        Returns:
            A dictionary containing the copied runtime fields captured on the
            normalized telemetry packet.
        """
        return {
            "value": self.runtime_value,
            "aux": self.runtime_aux,
            "time": self.runtime_time,
            "state": self.runtime_state,
            "position": self.runtime_position,
            "status": self.runtime_status,
        }

    def to_raw_event_payload(self) -> dict[str, Any]:
        """Build the canonical raw telemetry event payload for this packet.

        Returns:
            A raw-event payload containing the normalized device metadata plus
            nested ``packet`` and ``runtime`` summaries.
        """
        return {
            "event_kind": "telemetry_packet",
            "observed_at": self.wall_time,
            "source": self.source,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "device_type": self.device_type,
            "device_group": self.device_group,
            "device_systems": list(self.device_systems),
            "widget_type": self.widget_type,
            "bus_address": self.bus_address,
            "packet": self.packet_summary(),
            "runtime": self.runtime_summary(),
        }
