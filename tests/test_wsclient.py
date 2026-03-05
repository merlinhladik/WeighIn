import asyncio

import pytest

import wsclient


def test_websocket_client_connect_send_recv_and_close(monkeypatch):
    class DummyWS:
        def __init__(self):
            self.sent = []
            self.closed = False

        async def send(self, message):
            self.sent.append(message)

        async def recv(self):
            return '{"type":"ok","value":1}'

        async def close(self):
            self.closed = True

    async def _run():
        dummy = DummyWS()

        async def fake_connect(_url):
            return dummy

        monkeypatch.setattr(wsclient.websockets, "connect", fake_connect)

        client = wsclient.WebSocketClient("ws://example.test")
        await client.connect()
        await client.send_json({"type": "ping"})
        message = await client.recv_json()
        await client.close()

        assert dummy.sent == ['{"type": "ping"}']
        assert message == {"type": "ok", "value": 1}
        assert dummy.closed is True
        assert client._ws is None

    asyncio.run(_run())


def test_websocket_client_recv_json_returns_invalid_marker_for_bad_json():
    class DummyWS:
        async def recv(self):
            return "not-json"

    async def _run():
        client = wsclient.WebSocketClient("ws://example.test")
        client._ws = DummyWS()

        assert await client.recv_json() == {"type": "__INVALID__", "raw": "not-json"}

    asyncio.run(_run())


def test_weight_client_sends_weight_only_for_request():
    sent = []

    class DummyClient:
        async def send_json(self, payload):
            sent.append(payload)

    async def _run():
        client = wsclient.WeightClient(DummyClient(), lambda: "7564")
        await client.handle_message({"type": "IGNORED"})
        await client.handle_message({"type": "REQUEST_WEIGHT"})

    asyncio.run(_run())

    assert sent == [{"type": "weight", "weight": "7564"}]


def test_weight_client_skips_none_weight():
    sent = []

    class DummyClient:
        async def send_json(self, payload):
            sent.append(payload)

    async def _run():
        client = wsclient.WeightClient(DummyClient(), lambda: None)
        await client.handle_message({"type": "REQUEST_WEIGHT"})

    asyncio.run(_run())

    assert sent == []


def test_qr_client_wraps_info_payload():
    sent = []

    class DummyClient:
        async def send_json(self, payload):
            sent.append(payload)

    async def _run():
        client = wsclient.QRClient(DummyClient())
        await client.send_qr({"first_name": "Ada"})

    asyncio.run(_run())

    assert sent == [{"type": "qr", "info": {"first_name": "Ada"}}]


def test_websocket_client_requires_connection():
    client = wsclient.WebSocketClient("ws://example.test")

    async def _send():
        await client.send_json({"type": "ping"})

    async def _recv():
        await client.recv_json()

    with pytest.raises(RuntimeError, match="not connected"):
        asyncio.run(_send())

    with pytest.raises(RuntimeError, match="not connected"):
        asyncio.run(_recv())
