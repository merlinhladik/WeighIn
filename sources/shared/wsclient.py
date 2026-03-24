# wsclient.py
import json
from typing import Optional, Callable, Any
import websockets


class WebSocketDisconnected(RuntimeError):
    """Raised when the websocket connection was lost during send/recv."""


class WebSocketClient:
    """Persistent WebSocket client with explicit recv/send (no background tasks)."""

    def __init__(self, url: str):
        self.url = url
        self._ws: Optional[websockets.WebSocketClientProtocol] = None

    async def connect(self) -> None:
        """Open the websocket connection once."""
        if self._ws is not None:
            try:
                if not self._ws.closed:
                    return
            except Exception:
                pass
            self._ws = None
        self._ws = await websockets.connect(self.url, ping_interval=40, ping_timeout=40)

    async def close(self) -> None:
        """Close the websocket connection."""
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def reconnect(self) -> None:
        """Recreate the websocket connection after a disconnect."""
        await self.close()
        await self.connect()

    async def _handle_disconnect(self) -> None:
        """Drop a broken websocket instance so callers can reconnect cleanly."""
        ws = self._ws
        self._ws = None
        if ws is None:
            return
        try:
            await ws.close()
        except Exception:
            pass

    async def send_json(self, data: dict) -> None:
        """Send one JSON message."""
        if self._ws is None:
            raise WebSocketDisconnected("WebSocket is not connected.")
        try:
            await self._ws.send(json.dumps(data))
        except websockets.ConnectionClosed as exc:
            await self._handle_disconnect()
            raise WebSocketDisconnected("WebSocket connection lost during send.") from exc

    async def recv_json(self) -> dict:
        """Receive one message and parse JSON."""
        if self._ws is None:
            raise WebSocketDisconnected("WebSocket is not connected.")
        try:
            raw = await self._ws.recv()
        except websockets.ConnectionClosed as exc:
            await self._handle_disconnect()
            raise WebSocketDisconnected("WebSocket connection lost during recv.") from exc
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"type": "__INVALID__", "raw": raw}


class WeightClient:
    """Handles REQUEST_WEIGHT and replies with a weight value."""

    def __init__(self, ws: WebSocketClient, weight_provider: Callable[[], Any]):
        """
        Args:
            ws: Connected WebSocketClient instance.
            weight_provider: Function that returns the weight value (number or 'Fehler').
        """
        self.ws = ws
        self.weight_provider = weight_provider

    async def register(self) -> None:
        """Register this websocket as the weight client."""
        await self.ws.send_json({"type": "register", "role": "weight"})

    async def handle_message(self, msg: dict) -> None:
        """Handle control messages intended for the weight client."""
        if msg.get("type") != "REQUEST_WEIGHT":
            return

        weight_value = self.weight_provider()
        if weight_value is None:
            return
        else:
            await self.ws.send_json({"type": "weight", "weight": weight_value}) 

class QRClient:
    """Send data when a QR code is scanned"""

    def __init__(self, ws: WebSocketClient):
        self.ws = ws

    async def register(self) -> None:
        """Register this websocket as the QR scanner client."""
        await self.ws.send_json({
            "type": "register",
            "role": "scanner"
        })

    async def send_qr(self, info: dict):
        """Sends QR scan events to the GUI"""

        await self.ws.send_json({
            "type": "qr",
            "info": info
        })
