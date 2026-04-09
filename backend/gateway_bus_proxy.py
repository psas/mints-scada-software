# backend/gateway_bus_proxy.py

from __future__ import annotations

import logging

from nexus import DataPacket

from .gateway_client import GatewayClient

log = logging.getLogger(__name__)


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

    def send(self, message: DataPacket) -> None:
        packet_id = getattr(message, "id", None)
        packet_cmd = getattr(message, "cmd", None)
        log.info(
            "[GatewayBusProxy] send device_id=%s packet.id=%s(0x%02x) cmd=%s",
            self.device_id,
            packet_id,
            packet_id if isinstance(packet_id, int) else 0,
            f"0x{packet_cmd:02x}" if isinstance(packet_cmd, int) else packet_cmd,
        )
        responses = self.gateway_client.send_packet(
            device_id=self.device_id,
            packet=message,
        )
        if not responses:
            log.error("[GatewayBusProxy] no response from gateway for %s", self.device_id)
            raise RuntimeError(
                f"Gateway did not acknowledge outbound packet for {self.device_id}"
            )

        first = responses[0]
        log.info("[GatewayBusProxy] gateway response type=%s for %s", first.type, self.device_id)
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

        return None