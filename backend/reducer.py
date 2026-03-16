from __future__ import annotations

from typing import Any, Mapping

from .state_store import StateStore
from .telemetry_models import NormalizedTelemetryPacket


class Reducer:
    """Backend reducer with normalized telemetry input and light semantic decode.

    Current semantic targets:
    - pressure-like devices
    - temperature-like devices
    - valve / solenoid devices
    - flow-like devices
    - load / weight-like devices

    The reducer now consumes a normalized telemetry envelope so that bus packets,
    mock telemetry, and any future replay / ingest source all enter the state
    update path with the same shape.
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
        telemetry = NormalizedTelemetryPacket.from_meta_runtime_packet(
            meta=meta,
            runtime=runtime,
            packet=packet,
            source=source,
        )
        return self.apply_normalized_telemetry(telemetry=telemetry)

    def apply_normalized_telemetry(
        self,
        *,
        telemetry: NormalizedTelemetryPacket,
    ) -> dict[str, Any]:
        packet_summary = telemetry.packet_summary()
        semantic = self._semantic_decode(telemetry=telemetry)

        reduction = {
            "device_id": telemetry.device_id,
            "device_name": telemetry.device_name,
            "device_type": telemetry.device_type,
            "device_group": telemetry.device_group,
            "source": telemetry.source,
            "wall_time": telemetry.wall_time,
            "packet_count_increment": 1,
            "packet_summary": packet_summary,
            "runtime_value": telemetry.runtime_value,
            "runtime_aux": telemetry.runtime_aux,
            "runtime_time": telemetry.runtime_time,
            "runtime_state": telemetry.runtime_state,
            "runtime_position": telemetry.runtime_position,
            "runtime_status": telemetry.runtime_status,
            "semantic": semantic,
        }

        self.state_store.mark_device_packet(
            device_id=telemetry.device_id,
            wall_time=telemetry.wall_time,
            packet_id=telemetry.packet_id,
            packet_seq=telemetry.packet_seq,
            packet_cmd=telemetry.packet_cmd,
            packet_reply=telemetry.packet_reply,
            packet_err=telemetry.packet_err,
            packet_rsvd=telemetry.packet_rsvd,
            packet_timestamp=telemetry.packet_timestamp,
            packet_data=list(telemetry.packet_data),
            runtime_value=telemetry.runtime_value,
            runtime_aux=telemetry.runtime_aux,
            runtime_time=telemetry.runtime_time,
            source=telemetry.source,
        )

        return reduction

    def _semantic_decode(
        self,
        *,
        telemetry: NormalizedTelemetryPacket,
    ) -> dict[str, Any]:
        lowered_type = telemetry.device_type.strip().lower()
        lowered_name = telemetry.device_name.strip().lower()

        if self._looks_like_pressure(lowered_type, lowered_name):
            return self._decode_pressure(
                runtime_value=telemetry.runtime_value,
                runtime_aux=telemetry.runtime_aux,
                runtime_time=telemetry.runtime_time,
            )

        if self._looks_like_temperature(lowered_type, lowered_name):
            return self._decode_temperature(
                runtime_value=telemetry.runtime_value,
                runtime_aux=telemetry.runtime_aux,
                runtime_time=telemetry.runtime_time,
            )

        if self._looks_like_valve(lowered_type, lowered_name):
            return self._decode_valve(telemetry=telemetry)

        if self._looks_like_flow(lowered_type, lowered_name):
            return self._decode_flow(
                runtime_value=telemetry.runtime_value,
                runtime_aux=telemetry.runtime_aux,
                runtime_time=telemetry.runtime_time,
            )

        if self._looks_like_load(lowered_type, lowered_name):
            return self._decode_load(
                runtime_value=telemetry.runtime_value,
                runtime_aux=telemetry.runtime_aux,
                runtime_time=telemetry.runtime_time,
            )

        return {
            "domain": "generic",
            "summary": self._build_generic_summary(telemetry.runtime_value, telemetry.runtime_aux),
            "fields": {
                "value": telemetry.runtime_value,
                "aux": telemetry.runtime_aux,
                "time": telemetry.runtime_time,
                "state": telemetry.runtime_state,
                "position": telemetry.runtime_position,
                "status": telemetry.runtime_status,
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

    def _decode_valve(self, *, telemetry: NormalizedTelemetryPacket) -> dict[str, Any]:
        state = self._extract_valve_state(telemetry=telemetry)
        return {
            "domain": "valve",
            "summary": f"Valve state {state}",
            "fields": {
                "state": state,
                "sample_time": telemetry.runtime_time,
                "quality": self._extract_quality(telemetry.runtime_aux),
                "packet_reply": telemetry.packet_reply,
                "packet_err": telemetry.packet_err,
                "position": telemetry.runtime_position,
                "status": telemetry.runtime_status,
            },
        }

    def _extract_valve_state(self, *, telemetry: NormalizedTelemetryPacket) -> str:
        for candidate in (
            telemetry.runtime_state,
            telemetry.runtime_position,
            telemetry.runtime_status,
            telemetry.runtime_value,
        ):
            resolved = self._normalize_valve_state(candidate)
            if resolved is not None:
                return resolved

        if isinstance(telemetry.runtime_aux, Mapping):
            for key in ("state", "position", "status", "open"):
                resolved = self._normalize_valve_state(telemetry.runtime_aux.get(key))
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
