import threading
import time
import json
import asyncio
import websockets

class NetworkManager:
    """
    Handles communication with the Backend via WebSocket (Real Implementation).
    Run in a separate thread to avoid freezing the GUI.
    """
    def __init__(self, callback_on_message=None):
        self.connected = False
        self.running = False
        self.callback = callback_on_message
        self.ws_url = "ws://localhost:8000/ws" # Update to real backend URL
        self._thread = None
        self.loop = None
        self.websocket = None

    def start_connection(self):
        """Starts the connection loop in a background thread."""
        self.running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop_connection(self):
        """Stops the background thread."""
        self.running = False
        self.connected = False
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)

    def send_weight(self, participant_id, weight):
        """Sends weight data to the backend."""
        if not self.connected or not self.loop:
            print(f"[Network] Not connected. Cannot send {weight}kg for ID {participant_id}")
            return False
            
        payload = {
            "type": "WEIGH_IN",
            "participant_id": participant_id,
            "weight": weight,
            "timestamp": time.time()
        }
        
        # Schedule the send coroutine in the event loop (Thread-safe)
        asyncio.run_coroutine_threadsafe(self._send_payload(payload), self.loop)
        print(f"[Network] QUEUED >>> {json.dumps(payload)}")
        return True

    async def _send_payload(self, payload):
        """Async helper to send data."""
        try:
            if self.websocket:
                await self.websocket.send(json.dumps(payload))
        except Exception as e:
            print(f"[Network] Send Error: {e}")

    def _run_loop(self):
        """Entry point for the background thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._connect_to_server())

    async def _connect_to_server(self):
        """Keeps trying to connect to the server."""
        print(f"[Network] Starting connection loop to {self.ws_url}")
        
        while self.running:
            try:
                print(f"[Network] Connecting to {self.ws_url} ...")
                async with websockets.connect(self.ws_url) as ws:
                    self.websocket = ws
                    self.connected = True
                    print("[Network] CONNECTED! ✅")
                    
                    # Listen for messages
                    async for message in ws:
                        if not self.running: break
                        print(f"[Network] Received: {message}")
                        if self.callback:
                            try:
                                data = json.loads(message)
                                self.callback(data)
                            except:
                                pass
            except Exception as e:
                print(f"[Network] Connection Failed/Lost: {e}")
                self.connected = False
            
            # Reconnect delay
            if self.running:
                print("[Network] Retrying in 5 seconds...")
                await asyncio.sleep(5)
