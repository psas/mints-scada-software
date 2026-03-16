from __future__ import annotations

from typing import Any, Mapping

from historymanager.manager import isoformat_z

from .state_store import StateStore


class Reducer:
    """Backend reducer with light semantic decode for key device families.

    Current semantic targets:
    - pressure-like devices
    - temperature-like devices
    - valve / solenoid devices
    - flow-like devices
    - load / weight-like devices

    This still does not claim full protocol/business decode coverage for every
    hardware class, but it upgrades the old generic packet summary into
    domain-oriented structured fields where the runtime information is already
    available.
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

        packet_summary = {
            "id": packet.id,
            "seq": packet.seq,
            "cmd": packet.cmd,
            "reply": bool(packet.reply),
            "err": bool(packet.err),
            "rsvd": bool(packet.rsvd),
            "timestamp": getattr(packet, "timestamp", None),
            "data": list(packet.data),
            "data_hex": " ".join(f"{b:02X}" for b in packet.data),
        }

        semantic = self._semantic_decode(
            meta=meta,
            runtime=runtime,
            runtime_value=runtime_value,
            runtime_aux=runtime_aux,
            runtime_time=runtime_time,
            packet_summary=packet_summary,
        )

        reduction = {
            "device_id": meta["id"],
            "device_name": meta["name"],
            "device_type": meta["deviceType"],
            "device_group": meta["deviceGroup"],
            "source": source,
            "wall_time": wall_time,
            "packet_count_increment": 1,
            "packet_summary": packet_summary,
            "runtime_value": runtime_value,
            "runtime_aux": runtime_aux,
            "runtime_time": runtime_time,
            "semantic": semantic,
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

    def _semantic_decode(
        self,
        *,
        meta: Mapping[str, Any],
        runtime: Any,
        runtime_value: Any,
        runtime_aux: Any,
        runtime_time: Any,
        packet_summary: Mapping[str, Any],
    ) -> dict[str, Any]:
        device_type = str(meta.get("deviceType") or "")
        device_name = str(meta.get("name") or "")
        lowered_type = device_type.strip().lower()
        lowered_name = device_name.strip().lower()

        if self._looks_like_pressure(lowered_type, lowered_name):
            return self._decode_pressure(
                runtime_value=runtime_value,
                runtime_aux=runtime_aux,
                runtime_time=runtime_time,
            )

        if self._looks_like_temperature(lowered_type, lowered_name):
            return self._decode_temperature(
                runtime_value=runtime_value,
                runtime_aux=runtime_aux,
                runtime_time=runtime_time,
            )

        if self._looks_like_valve(lowered_type, lowered_name):
            return self._decode_valve(
                runtime=runtime,
                runtime_value=runtime_value,
                runtime_aux=runtime_aux,
                runtime_time=runtime_time,
                packet_summary=packet_summary,
            )

        if self._looks_like_flow(lowered_type, lowered_name):
            return self._decode_flow(
                runtime_value=runtime_value,
                runtime_aux=runtime_aux,
                runtime_time=runtime_time,
            )

        if self._looks_like_load(lowered_type, lowered_name):
            return self._decode_load(
                runtime_value=runtime_value,
                runtime_aux=runtime_aux,
                runtime_time=runtime_time,
            )

        return {
            "domain": "generic",
            "summary": self._build_generic_summary(runtime_value, runtime_aux),
            "fields": {
                "value": runtime_value,
                "aux": runtime_aux,
                "time": runtime_time,
            },
        }

    def _decode_pressure(
        self,
        *,
        runtime_value: Any,
        runtime_aux: Any,
        runtime_time: Any,
    ) -> dict[str, Any]:
        value = self._coerce_number(runtime_value)
        units = self._extract_units(runtime_aux, fallback="psi")
        return {
            "domain": "pressure",
            "summary": self._number_summary("Pressure", value, units),
            "fields": {
                "pressure": value,
                "units": units,
                "sample_time": runtime_time,
                "quality": self._extract_quality(runtime_aux),
            },
        }

    def _decode_temperature(
        self,
        *,
        runtime_value: Any,
        runtime_aux: Any,
        runtime_time: Any,
    ) -> dict[str, Any]:
        value = self._coerce_number(runtime_value)
        units = self._extract_units(runtime_aux, fallback="C")
        return {
            "domain": "temperature",
            "summary": self._number_summary("Temperature", value, units),
            "fields": {
                "temperature": value,
                "units": units,
                "sample_time": runtime_time,
                "quality": self._extract_quality(runtime_aux),
            },
        }

    def _decode_flow(
        self,
        *,
        runtime_value: Any,
        runtime_aux: Any,
        runtime_time: Any,
    ) -> dict[str, Any]:
        value = self._coerce_number(runtime_value)
        units = self._extract_units(runtime_aux, fallback="unknown")
        return {
            "domain": "flow",
            "summary": self._number_summary("Flow", value, units),
            "fields": {
                "flow": value,
                "units": units,
                "sample_time": runtime_time,
                "quality": self._extract_quality(runtime_aux),
            },
        }

    def _decode_load(
        self,
        *,
        runtime_value: Any,
        runtime_aux: Any,
        runtime_time: Any,
    ) -> dict[str, Any]:
        value = self._coerce_number(runtime_value)
        units = self._extract_units(runtime_aux, fallback="unknown")
        return {
            "domain": "load",
            "summary": self._number_summary("Load", value, units),
            "fields": {
                "load": value,
                "units": units,
                "sample_time": runtime_time,
                "quality": self._extract_quality(runtime_aux),
            },
        }

    def _decode_valve(
        self,
        *,
        runtime: Any,
        runtime_value: Any,
        runtime_aux: Any,
        runtime_time: Any,
        packet_summary: Mapping[str, Any],
    ) -> dict[str, Any]:
        state = self._extract_valve_state(runtime=runtime, runtime_value=runtime_value, runtime_aux=runtime_aux)
        return {
            "domain": "valve",
            "summary": f"Valve state {state}",
            "fields": {
                "state": state,
                "sample_time": runtime_time,
                "quality": self._extract_quality(runtime_aux),
                "packet_reply": packet_summary.get("reply"),
                "packet_err": packet_summary.get("err"),
            },
        }

    def _extract_valve_state(self, *, runtime: Any, runtime_value: Any, runtime_aux: Any) -> str:
        for attr_name in ("state", "position", "status"):
            attr_value = getattr(runtime, attr_name, None)
            resolved = self._normalize_valve_state(attr_value)
            if resolved is not None:
                return resolved

        resolved = self._normalize_valve_state(runtime_value)
        if resolved is not None:
            return resolved

        if isinstance(runtime_aux, Mapping):
            for key in ("state", "position", "status", "open"):
                resolved = self._normalize_valve_state(runtime_aux.get(key))
                if resolved is not None:
                    return resolved

        return "unknown"

    def _normalize_valve_state(self, value: Any) -> str | None:
        if isinstance(value, bool):
            return "open" if value else "closed"

        if isinstance(value, (int, float)):
            if value >= 0.75:
                return "open"
            if value <= 0.25:
                return "closed"
            return "partial"

        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"open", "opened", "on"}:
                return "open"
            if lowered in {"closed", "close", "off"}:
                return "closed"
            if lowered in {"partial", "opening", "closing", "moving"}:
                return lowered if lowered != "close" else "closed"

        return None

    def _extract_units(self, runtime_aux: Any, *, fallback: str) -> str:
        if isinstance(runtime_aux, Mapping):
            units = runtime_aux.get("units") or runtime_aux.get("unit")
            if isinstance(units, str) and units.strip():
                return units.strip()
        return fallback

    def _extract_quality(self, runtime_aux: Any) -> str | None:
        if isinstance(runtime_aux, Mapping):
            quality = runtime_aux.get("quality")
            if isinstance(quality, str) and quality.strip():
                return quality.strip()
        return None

    def _coerce_number(self, value: Any) -> float | int | None:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return value
        return None

    def _number_summary(self, label: str, value: float | int | None, units: str) -> str:
        if value is None:
            return f"{label} unavailable"
        return f"{label} {value} {units}".strip()

    def _build_generic_summary(self, runtime_value: Any, runtime_aux: Any) -> str:
        if runtime_value is not None:
            return f"Value={runtime_value!r}"
        if runtime_aux is not None:
            return f"Aux={runtime_aux!r}"
        return "No semantic decode available"

    def _looks_like_pressure(self, lowered_type: str, lowered_name: str) -> bool:
        return any(token in lowered_type or token in lowered_name for token in ("pressure", "press", "psi", "pt"))

    def _looks_like_temperature(self, lowered_type: str, lowered_name: str) -> bool:
        return any(token in lowered_type or token in lowered_name for token in ("temperature", "temp", "thermocouple", "tc"))

    def _looks_like_valve(self, lowered_type: str, lowered_name: str) -> bool:
        return any(token in lowered_type or token in lowered_name for token in ("valve", "solenoid", "xv", "mv"))

    def _looks_like_flow(self, lowered_type: str, lowered_name: str) -> bool:
        return any(token in lowered_type or token in lowered_name for token in ("flow", "massflow", "mfc"))

    def _looks_like_load(self, lowered_type: str, lowered_name: str) -> bool:
        return any(token in lowered_type or token in lowered_name for token in ("load", "weight", "force", "thrust", "scale"))
