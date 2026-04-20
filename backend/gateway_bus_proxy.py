"""backend/gateway_bus_proxy.py

Gateway-backed bus proxy for backend outbound packet dispatch.

This module provides a small bus-like adapter that lets backend command paths
send ``DataPacket`` instances through the gateway service while preserving a
send-style interface for callers.
"""

from __future__ import annotations

import logging

from nexus import DataPacket

from .gateway_client import GatewayClient

log = logging.getLogger(__name__)


class GatewayBusProxy:
    """Forward outbound packet sends to the gateway for a specific device.

    The proxy presents a minimal bus-like interface to backend callers. Its
    ``send`` method dispatches a ``DataPacket`` through ``GatewayClient``,
    validates the first gateway response, and raises a runtime error when the
    gateway rejects or fails to acknowledge the outbound packet.
    """

    def __init__(
        self,
        *,
        gateway_client: GatewayClient,
        device_id: str,
    ) -> None:
        """Initialize the proxy for one backend-visible device.

        Args:
            gateway_client: Gateway client used to send outbound packets to the
                gateway service.
            device_id: Canonical device identifier associated with this proxy.
        """
        self.gateway_client = gateway_client
        self.device_id = device_id

    def send(self, message: DataPacket) -> None:
        """Send an outbound packet through the gateway and validate the reply.

        The gateway is expected to acknowledge successful sends with a first
        response of type ``packet_sent``. Error responses and missing
        acknowledgements are surfaced as ``RuntimeError`` exceptions so backend
        command paths can treat the send as failed.

        Args:
            message: Outbound packet to send through the gateway.

        Returns:
            None.

        Raises:
            RuntimeError: The gateway did not respond, returned an error
                response, or returned an unexpected response type.
        """
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
            log.error(
                "[GatewayBusProxy] no response from gateway for %s", self.device_id
            )
            raise RuntimeError(
                f"Gateway did not acknowledge outbound packet for {self.device_id}"
            )

        first = responses[0]
        log.info(
            "[GatewayBusProxy] gateway response type=%s for %s",
            first.type,
            self.device_id,
        )
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
