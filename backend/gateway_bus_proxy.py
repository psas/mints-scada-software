from __future__ import annotations

from typing import Any, Mapping

from nexus import DataPacket

from .gateway_client import GatewayClient


class GatewayBusProxy:
    """Bus-like proxy that forwards outbound DataPacket sends to gateway."""

    def __init__(
        self,
        *,
        gateway_client: GatewayClient,
        device_id: str,
    ) -> None:
        self.gateway_client = gateway_client
        self.device_id = device_id
        self._last_sent_raw_event: dict[str, Any] | None = None

    def consume_last_sent_raw_event(self) -> dict[str, Any] | None:
        event = self._last_sent_raw_event
        self._last_sent_raw_event = None
        return event

    def send(self, message: DataPacket) -> None:
        responses = self.gateway_client.send_packet(
            device_id=self.device_id,
            packet=message,
        )
        if not responses:
            raise RuntimeError(
                f"Gateway did not acknowledge outbound packet for {self.device_id}"
            )

        first = responses[0]
        if first.type == "error":
            code = None
            message_text = "gateway rejected outbound packet"
            if isinstance(first.payload, dict):
                code = first.payload.get("code")
                message_text = str(first.payload.get("message") or message_text)
            if code:
                raise RuntimeError(f"{code}: {message_text}")
            raise RuntimeError(message_text)

        if first.type != "packet_sent":
            raise RuntimeError(
                f"Unexpected gateway response type for outbound packet: {first.type}"
            )

        raw_event = None
        if isinstance(first.payload, Mapping):
            candidate = first.payload.get("event")
            if isinstance(candidate, Mapping):
                raw_event = dict(candidate)

        self._last_sent_raw_event = raw_event
        return None