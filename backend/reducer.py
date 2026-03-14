from __future__ import annotations

from typing import Any

from historymanager.manager import isoformat_z

from .state_store import StateStore


class Reducer:
    """Minimal backend reducer.

    Current scope:
    - accept a packet already associated with a runtime device
    - update authoritative device runtime state
    - return a compact reduction summary for structured event building

    This intentionally does not attempt full protocol/business decoding yet.
    """

    def __init__(self, *, state_store: StateStore) -> None:
        self.state_store = state_store

    def apply_telemetry_packet(
        self,
        *,
        meta: dict[str, Any],
        runtime: Any,
        packet: Any,
        source: str = "bus",
    ) -> dict[str, Any]:
        wall_time = isoformat_z()

        runtime_value = getattr(runtime, "value", None)
        runtime_aux = getattr(runtime, "aux", None)
        runtime_time = getattr(runtime, "time", None)

        reduction = {
            "device_id": meta["id"],
            "device_name": meta["name"],
            "device_type": meta["deviceType"],
            "device_group": meta["deviceGroup"],
            "source": source,
            "wall_time": wall_time,
            "packet_count_increment": 1,
            "packet_summary": {
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
            "runtime_value": runtime_value,
            "runtime_aux": runtime_aux,
            "runtime_time": runtime_time,
        }

        self.state_store.mark_device_packet(
            device_id=meta["id"],
            wall_time=wall_time,
            packet_id=packet.id,
            packet_seq=packet.seq,
            packet_cmd=packet.cmd,
            packet_reply=bool(packet.reply),
            packet_err=bool(packet.err),
            packet_rsvd=bool(packet.rsvd),
            packet_timestamp=getattr(packet, "timestamp", None),
            packet_data=list(packet.data),
            runtime_value=runtime_value,
            runtime_aux=runtime_aux,
            runtime_time=runtime_time,
            source=source,
        )

        return reduction