import asyncio
import json

import websockets

from gui import WeighingApp


class DummyApp:
    filter_qr = WeighingApp.filter_qr
    _ws_handler = WeighingApp._ws_handler

    def __init__(self):
        self.ws_clients = set()
        self.received_weight = None
        self.received_name = None

    def after(self, _delay_ms, callback):
        callback()

    def apply_received_weight(self, weight):
        self.received_weight = weight

    def apply_qr_search(self, name):
        self.received_name = name

    def handle_incoming_qr(self, qr_data):
        self.apply_qr_search(qr_data.get("name", ""))


async def _start_test_server(app):
    server = await websockets.serve(app._ws_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, f"ws://127.0.0.1:{port}"


def test_ws_e2e_weight_and_validation():
    async def _run():
        app = DummyApp()
        server, url = await _start_test_server(app)
        try:
            async with websockets.connect(url) as ws:
                ready = json.loads(await ws.recv())
                assert ready["type"] == "SERVER_READY"

                await ws.send(json.dumps({"type": "weight", "weight": "7564"}))
                ack_ok = json.loads(await ws.recv())

                await ws.send(json.dumps({"type": "weight", "weight": "abc"}))
                ack_bad = json.loads(await ws.recv())

                await ws.send("not-json")
                ack_json = json.loads(await ws.recv())

            assert ack_ok["type"] == "ack"
            assert ack_ok["message"] == "weight accepted"
            assert ack_ok["weight"] == 7564
            assert app.received_weight == 7564

            assert ack_bad["type"] == "error"
            assert ack_bad["message"] == "field 'weight' must be int"

            assert ack_json["type"] == "error"
            assert ack_json["message"] == "invalid json"
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(_run())


def test_ws_e2e_qr_flow():
    async def _run():
        app = DummyApp()
        server, url = await _start_test_server(app)
        try:
            async with websockets.connect(url) as ws:
                _ = await ws.recv()  # SERVER_READY
                await ws.send(
                    json.dumps(
                        {
                            "type": "qr",
                            "info": {"first_name": "Ada", "last_name": "Lovelace", "exp_timestamp": 1},
                        }
                    )
                )
                ack = json.loads(await ws.recv())

            assert ack["type"] == "ack"
            assert ack["message"] == "qr accepted"
            assert ack["qr"]["name"] == "Ada Lovelace"
            assert app.received_name == "Ada Lovelace"
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(_run())
