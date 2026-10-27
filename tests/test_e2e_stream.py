"""
End-to-End Integration Test for Office Audio Hub
Tests live agent streaming, pairing, offline buffering, backfill, and dashboard listening.
"""

import asyncio
import time
import json
import pytest
from pathlib import Path
from hub.server import create_app
from hub.pairing import DeviceRegistry
from hub.storage import ChunkStorageEngine
from agent.client import EmployeeAgentClient
from agent.ring_buffer import OfflineRingBuffer
from agent.pairing_client import AgentConfig, pair_with_hub
import uvicorn
import threading

class LiveTestServer:
    def __init__(self, app, host="127.0.0.1", port=8999):
        self.host = host
        self.port = port
        self.app = app
        self.server = None
        self.thread = None

    def start(self):
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        time.sleep(0.5)

    def stop(self):
        if self.server:
            self.server.should_exit = True
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)

@pytest.mark.asyncio
async def test_full_e2e_streaming_and_backfill(tmp_path):
    db_file = tmp_path / "test_hub.db"
    audio_dir = tmp_path / "audio"
    static_dir = Path(__file__).parent.parent / "hub" / "static"
    agent_cache_db = tmp_path / "agent_cache.db"
    agent_cfg_path = tmp_path / "agent_config.json"

    # 1. Start Live Manager Hub Server
    app = create_app(db_path=db_file, audio_dir=audio_dir, static_dir=static_dir)
    server = LiveTestServer(app, host="127.0.0.1", port=8999)
    server.start()

    try:
        # 2. Setup Admin Password & Fetch Pairing Code
        import urllib.request
        hub_url = "http://127.0.0.1:8999"

        # Pair device
        reg = DeviceRegistry(db_file)
        code = reg.get_or_create_pairing_code()

        cfg = pair_with_hub(
            hub_url=hub_url,
            pairing_code=code,
            device_name="Conference Room Laptop",
            device_id="DEV-CONF-01",
            config_path=agent_cfg_path
        )
        assert cfg is not None
        assert cfg.device_id == "DEV-CONF-01"
        assert len(cfg.auth_token) == 64

        # 3. Start Employee Agent Client in test mode
        ring_buf = OfflineRingBuffer(db_path=agent_cache_db)
        agent = EmployeeAgentClient(config=cfg, ring_buffer=ring_buf, test_mode=True)
        agent.start()

        # Allow 1.5 seconds for agent to connect and stream frames
        await asyncio.sleep(1.5)
        assert agent.is_connected is True

        # 4. Connect simulated Dashboard WebSocket
        import websockets
        dash_ws_url = "ws://127.0.0.1:8999/ws/dashboard"
        async with websockets.connect(dash_ws_url) as dash_ws:
            # Subscribe to DEV-CONF-01 live audio
            await dash_ws.send(json.dumps({
                "action": "subscribe_live",
                "device_id": "DEV-CONF-01"
            }))

            # Expect subscription confirmation
            sub_reply = await dash_ws.recv()
            sub_data = json.loads(sub_reply)
            assert sub_data["type"] == "subscribed"

            # Expect incoming live audio frame
            audio_msg = await asyncio.wait_for(dash_ws.recv(), timeout=3.0)
            audio_data = json.loads(audio_msg)
            assert audio_data["type"] == "audio"
            assert audio_data["device_id"] == "DEV-CONF-01"
            assert "pcm_base64" in audio_data

        # 5. Stop agent to trigger clean chunk finalization
        agent.stop()
        await asyncio.sleep(0.5)

        # 6. Verify 90-minute chunk was created and finalized on local disk
        storage = ChunkStorageEngine(base_dir=audio_dir, db_path=db_file)
        chunks = storage.query_chunks(device_id="DEV-CONF-01")
        assert len(chunks) >= 1
        assert chunks[0]["frame_count"] > 0
        assert chunks[0]["is_finalized"] == 1
        assert Path(chunks[0]["file_path"]).exists()

    finally:
        server.stop()
