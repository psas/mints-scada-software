"""backend/reducer.py

Reducer for translating normalized telemetry into backend state updates.

This module accepts normalized telemetry envelopes, derives lightweight
domain-specific semantic summaries, and records per-device packet metadata into
the authoritative ``StateStore``.
"""

from __future__ import annotations

from typing import Any, Mapping

from .state_store import StateStore
from .telemetry_models import NormalizedTelemetryPacket


class Reducer:
    """Reduce normalized telemetry into semantic summaries and state-store updates.

    The reducer is the semantic translation layer between incoming telemetry and
    backend runtime state. It accepts either legacy ``meta``/``runtime``/``packet``
    inputs or an already-normalized telemetry envelope, derives a domain-specific
    semantic view when possible, and records the packet into ``StateStore`` as the
    authoritative per-device update.

    Current semantic targets include pressure, temperature, valve, flow, and
    load-like devices.
    """

    def __init__(self, *, state_store: StateStore) -> None:
        """Initialize the reducer with the authoritative state store.

        Args:
            state_store: Backend runtime state store that receives packet-level
                device updates.
        """
        self.state_store = state_store

    def apply_telemetry_packet(
        self,
        *,
        meta: dict[str, Any],
        runtime: Any,
        packet: Any,
        source: str = "bus",
    ) -> dict[str, Any]:
        """Normalize a raw telemetry input triple and apply it to backend state.

        Args:
            meta: Device or transport metadata used to build the normalized
                telemetry envelope.
            runtime: Runtime-decoded telemetry object or value bundle.
            packet: Underlying packet object associated with the telemetry.
            source: Source label for the telemetry path, such as live bus or
                mock ingest.

        Returns:
            The reduction dictionary produced from the normalized telemetry
            packet.
        """
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
        """Reduce a normalized telemetry envelope and update the state store.

        The returned reduction contains device identity, packet/runtime fields,
        and the semantic decode result. As a side effect, the packet is recorded
        into ``StateStore`` through ``mark_device_packet``.

        Args:
            telemetry: Normalized telemetry envelope to reduce.

        Returns:
            A reduction dictionary containing device metadata, packet summary,
            runtime fields, and the derived semantic payload.
        """
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
        """Build the semantic payload for a normalized telemetry envelope.

        The decoder chooses a domain-specific representation by applying simple
        type/name heuristics. When no known domain matches, it falls back to a
        generic payload that preserves the runtime fields without further
        interpretation.

        Args:
            telemetry: Normalized telemetry envelope to classify and decode.

        Returns:
            A semantic payload dictionary for the detected device domain.
        """
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
            "summary": self._build_generic_summary(
                telemetry.runtime_value, telemetry.runtime_aux
            ),
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
        """Build the semantic payload for a pressure-like device.

        Args:
            runtime_value: Primary runtime value from the telemetry envelope.
            runtime_aux: Auxiliary runtime payload, potentially including units
                and quality.
            runtime_time: Runtime sample timestamp or time marker.

        Returns:
            A pressure-domain semantic payload with normalized numeric value,
            units, sample time, and optional quality.
        """
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
        """Build the semantic payload for a temperature-like device.

        Args:
            runtime_value: Primary runtime value from the telemetry envelope.
            runtime_aux: Auxiliary runtime payload, potentially including units
                and quality.
            runtime_time: Runtime sample timestamp or time marker.

        Returns:
            A temperature-domain semantic payload with normalized numeric value,
            units, sample time, and optional quality.
        """
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
        """Build the semantic payload for a flow-like device.

        Args:
            runtime_value: Primary runtime value from the telemetry envelope.
            runtime_aux: Auxiliary runtime payload, potentially including units
                and quality.
            runtime_time: Runtime sample timestamp or time marker.

        Returns:
            A flow-domain semantic payload with normalized numeric value, units,
            sample time, and optional quality.
        """
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
        """Build the semantic payload for a load-like device.

        Args:
            runtime_value: Primary runtime value from the telemetry envelope.
            runtime_aux: Auxiliary runtime payload, potentially including units
                and quality.
            runtime_time: Runtime sample timestamp or time marker.

        Returns:
            A load-domain semantic payload with normalized numeric value, units,
            sample time, and optional quality.
        """
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
        """Build the semantic payload for a valve-like device.

        Args:
            telemetry: Normalized telemetry envelope to decode.

        Returns:
            A valve-domain semantic payload with normalized valve state and
            related packet/runtime fields that help describe the current valve
            reading.
        """
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
        """Resolve the best available valve state from a telemetry envelope.

        The lookup prefers explicit runtime state-like fields before falling
        back to known keys inside ``runtime_aux``.

        Args:
            telemetry: Normalized telemetry envelope to inspect.

        Returns:
            The normalized valve state, or ``"unknown"`` when no state-like
            field can be interpreted.
        """
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
        """Normalize a raw valve state value into a canonical state string.

        Bool values map to ``open`` or ``closed``. Numeric values use threshold
        ranges to produce ``open``, ``closed``, or ``partial``. Known textual
        states are normalized to lowercase backend-friendly labels.

        Args:
            value: Raw state candidate to normalize.

        Returns:
            The canonical valve state string, or None when the value cannot be
            interpreted as a valve state.
        """
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
        """Extract units from auxiliary runtime data.

        Args:
            runtime_aux: Auxiliary runtime payload that may contain ``units`` or
                ``unit``.
            fallback: Units string to return when auxiliary data does not define
                one.

        Returns:
            The extracted units string, or the provided fallback.
        """
        if isinstance(runtime_aux, Mapping):
            units = runtime_aux.get("units") or runtime_aux.get("unit")
            if isinstance(units, str) and units.strip():
                return units.strip()
        return fallback

    def _extract_quality(self, runtime_aux: Any) -> str | None:
        """Extract a quality label from auxiliary runtime data.

        Args:
            runtime_aux: Auxiliary runtime payload that may contain ``quality``.

        Returns:
            The stripped quality string, or None when auxiliary data does not
            define one.
        """
        if isinstance(runtime_aux, Mapping):
            quality = runtime_aux.get("quality")
            if isinstance(quality, str) and quality.strip():
                return quality.strip()
        return None

    def _coerce_number(self, value: Any) -> float | int | None:
        """Convert a runtime value into a numeric form when possible.

        Bool values are converted to ``0`` or ``1`` so they can still
        participate in numeric summaries.

        Args:
            value: Raw runtime value to inspect.

        Returns:
            A numeric value, or None when the input is not numeric.
        """
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return value
        return None

    def _number_summary(self, label: str, value: float | int | None, units: str) -> str:
        """Build a human-readable summary for a numeric semantic reading.

        Args:
            label: Domain label to place at the start of the summary.
            value: Numeric reading value.
            units: Units label for the reading.

        Returns:
            A formatted summary string, or an ``unavailable`` summary when no
            numeric value is present.
        """
        if value is None:
            return f"{label} unavailable"
        return f"{label} {value} {units}".strip()

    def _build_generic_summary(self, runtime_value: Any, runtime_aux: Any) -> str:
        """Build the fallback summary for telemetry without semantic decoding.

        Args:
            runtime_value: Primary runtime value from the telemetry envelope.
            runtime_aux: Auxiliary runtime payload from the telemetry envelope.

        Returns:
            A summary derived from the runtime value or auxiliary payload, or a
            no-decode message when neither is present.
        """
        if runtime_value is not None:
            return f"Value={runtime_value!r}"
        if runtime_aux is not None:
            return f"Aux={runtime_aux!r}"
        return "No semantic decode available"

    def _looks_like_pressure(self, lowered_type: str, lowered_name: str) -> bool:
        """Return whether device metadata suggests a pressure-like signal.

        Args:
            lowered_type: Lowercased device type.
            lowered_name: Lowercased device name.

        Returns:
            True when known pressure tokens appear in the type or name.
        """
        return any(
            token in lowered_type or token in lowered_name
            for token in ("pressure", "press", "psi", "pt")
        )

    def _looks_like_temperature(self, lowered_type: str, lowered_name: str) -> bool:
        """Return whether device metadata suggests a temperature-like signal.

        Args:
            lowered_type: Lowercased device type.
            lowered_name: Lowercased device name.

        Returns:
            True when known temperature tokens appear in the type or name.
        """
        return any(
            token in lowered_type or token in lowered_name
            for token in ("temperature", "temp", "thermocouple", "tc")
        )

    def _looks_like_valve(self, lowered_type: str, lowered_name: str) -> bool:
        """Return whether device metadata suggests a valve-like signal.

        Args:
            lowered_type: Lowercased device type.
            lowered_name: Lowercased device name.

        Returns:
            True when known valve or solenoid tokens appear in the type or name.
        """
        return any(
            token in lowered_type or token in lowered_name
            for token in ("valve", "solenoid", "xv", "mv")
        )

    def _looks_like_flow(self, lowered_type: str, lowered_name: str) -> bool:
        """Return whether device metadata suggests a flow-like signal.

        Args:
            lowered_type: Lowercased device type.
            lowered_name: Lowercased device name.

        Returns:
            True when known flow tokens appear in the type or name.
        """
        return any(
            token in lowered_type or token in lowered_name
            for token in ("flow", "massflow", "mfc")
        )

    def _looks_like_load(self, lowered_type: str, lowered_name: str) -> bool:
        """Return whether device metadata suggests a load-like signal.

        Args:
            lowered_type: Lowercased device type.
            lowered_name: Lowercased device name.

        Returns:
            True when known load, force, weight, or thrust tokens appear in the
            type or name.
        """
        return any(
            token in lowered_type or token in lowered_name
            for token in ("load", "weight", "force", "thrust", "scale")
        )
