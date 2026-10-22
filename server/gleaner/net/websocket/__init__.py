"""自研 WebSocket（RFC 6455）。"""

from .protocol import (
    CloseCode,
    Closed,
    Message,
    Opcode,
    WSConnection,
    WSProtocolError,
    accept_key,
    encode_frame,
    handshake_response,
    mask_bytes,
)
from .stream import ConnectionClosed, HandshakeError, WebSocket, connect, websocket_route

__all__ = [
    "CloseCode",
    "Closed",
    "ConnectionClosed",
    "HandshakeError",
    "Message",
    "Opcode",
    "WSConnection",
    "WSProtocolError",
    "WebSocket",
    "accept_key",
    "connect",
    "encode_frame",
    "handshake_response",
    "mask_bytes",
    "websocket_route",
]
