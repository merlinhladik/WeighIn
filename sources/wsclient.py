# wsclient.py
import json
from typing import Optional, Callable, Any
import websockets


class WebSocketClient:
    """Persistent WebSocket client with explicit recv/send (no background tasks)."""

    def __init__(self, url: str):
        self.url = url
        self._ws: Optional[websockets.WebSocketClientProtocol] = None

    async def connect(self) -> None:
        """Open the websocket connection once."""
        self._ws = await websockets.connect(self.url)

    async def close(self) -> None:
        """Close the websocket connection."""
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def send_json(self, data: dict) -> None:
        """Send one JSON message."""
        if self._ws is None:
            raise RuntimeError("WebSocket is not connected.")
        await self._ws.send(json.dumps(data))

    async def recv_json(self) -> dict:
        """Receive one message and parse JSON."""
        if self._ws is None:
            raise RuntimeError("WebSocket is not connected.")
        raw = await self._ws.recv()
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

    async def handle_message(self, msg: dict) -> None:
        """If msg is REQUEST_WEIGHT, send weight immediately."""
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

    async def send_qr(self, info: dict):
        """Sends QR scan events to the GUI"""

        await self.ws.send_json({
            "type": "qr",
            "info": info
        })