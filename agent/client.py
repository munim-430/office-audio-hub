"""
Employee Agent Streaming Client Engine
Orchestrates audio capture, Opus encoding, continuous WebSocket transmission,
offline ring buffering, and prioritized backfill.
"""

import asyncio
import json
import time
import queue
import logging
import threading
from typing import Optional, Callable
import websockets

from common.config import WS_AUDIO_STREAM_PATH, FRAME_DURATION_MS
from common.protocol import (
    PacketType,
    encode_audio_packet,
    decode_audio_packet,
    create_heartbeat_ping
)
from common.audio_format import AudioEncoder
from agent.capture import AudioCaptureSupervisor
from agent.ring_buffer import OfflineRingBuffer
from agent.pairing_client import AgentConfig

logger = logging.getLogger("AgentClient")

class EmployeeAgentClient:
    """Manages 24/7 background audio capture and streaming to Manager Hub."""
    def __init__(
        self,
        config: AgentConfig,
        ring_buffer: Optional[OfflineRingBuffer] = None,
        test_mode: bool = False
    ):
        self.config = config
        self.ring_buffer = ring_buffer or OfflineRingBuffer()
        self.test_mode = test_mode

        self.audio_encoder = AudioEncoder()
        self.raw_frame_queue: queue.Queue = queue.Queue(maxsize=200)
        self.stop_event = threading.Event()
        
        self.capture_supervisor = AudioCaptureSupervisor(
            on_frame_captured=self._on_frame_captured,
            test_mode=self.test_mode
        )

        self.ws_connection = None
        self.is_connected = False
        self.seq_num = 0
        self.status_callback: Optional[Callable[[str], None]] = None

    def _on_frame_captured(self, raw_pcm: bytes):
        """Called by the audio capture thread (every 20ms)."""
        try:
            self.raw_frame_queue.put_nowait(raw_pcm)
        except queue.Full:
            try:
                self.raw_frame_queue.get_nowait()
                self.raw_frame_queue.put_nowait(raw_pcm)
            except queue.Empty:
                pass

    def start(self):
        """Starts capture and streaming loops."""
        self.stop_event.clear()
        self.capture_supervisor.start()
        self.client_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.client_thread.start()
        logger.info("Employee Agent Client started for device: %s", self.config.device_id)

    def stop(self):
        self.stop_event.set()
        self.capture_supervisor.stop()
        if hasattr(self, "client_thread") and self.client_thread.is_alive():
            self.client_thread.join(timeout=3.0)
        logger.info("Employee Agent Client stopped")

    def _run_async_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._main_streaming_loop())
        finally:
            loop.close()

    async def _main_streaming_loop(self):
        ws_url = self.config.hub_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_endpoint = f"{ws_url}{WS_AUDIO_STREAM_PATH}"

        backoff = 1.0
        while not self.stop_event.is_set():
            try:
                logger.info("Connecting to Manager Hub at %s...", ws_endpoint)
                if self.status_callback:
                    self.status_callback("Connecting...")

                async with websockets.connect(ws_endpoint, max_size=10 * 1024 * 1024) as ws:
                    self.ws_connection = ws
                    self.is_connected = True
                    backoff = 1.0
                    logger.info("WebSocket connected. Performing authentication handshake...")

                    # 1. Send AUTH_REQUEST
                    auth_payload = json.dumps({
                        "device_id": self.config.device_id,
                        "auth_token": self.config.auth_token
                    }).encode("utf-8")
                    auth_pkt = encode_audio_packet(
                        packet_type=PacketType.AUTH_REQUEST,
                        device_id=self.config.device_id,
                        timestamp_ms=int(time.time() * 1000),
                        sequence_num=0,
                        payload=auth_payload
                    )
                    await ws.send(auth_pkt)

                    # 2. Wait for AUTH_RESPONSE
                    auth_reply_bytes = await ws.recv()
                    auth_reply = decode_audio_packet(auth_reply_bytes)
                    if auth_reply.packet_type != PacketType.AUTH_RESPONSE:
                        raise ConnectionRefusedError("Hub rejected authentication")

                    logger.info("Authentication confirmed. Active live streaming engaged.")
                    if self.status_callback:
                        self.status_callback("Active & Streaming")

                    # Launch concurrent background backfill worker
                    backfill_task = asyncio.create_task(self._backfill_worker(ws))

                    # Continuous streaming & heartbeat loop
                    last_ping_time = time.time()
                    while not self.stop_event.is_set():
                        # Drain captured frames
                        frames_sent = 0
                        while True:
                            try:
                                raw_pcm = self.raw_frame_queue.get_nowait()
                            except queue.Empty:
                                break

                            opus_packet = self.audio_encoder.encode(raw_pcm)
                            self.seq_num = (self.seq_num + 1) & 0xFFFFFFFF
                            now_ms = int(time.time() * 1000)

                            pkt = encode_audio_packet(
                                packet_type=PacketType.AUDIO_FRAME,
                                device_id=self.config.device_id,
                                timestamp_ms=now_ms,
                                sequence_num=self.seq_num,
                                payload=opus_packet
                            )
                            await ws.send(pkt)
                            frames_sent += 1

                        # Periodic keep-alive ping (every 10s)
                        if time.time() - last_ping_time > 10.0:
                            ping_pkt = create_heartbeat_ping(self.config.device_id, self.seq_num)
                            await ws.send(ping_pkt)
                            last_ping_time = time.time()

                        await asyncio.sleep(0.01)

                    backfill_task.cancel()

            except Exception as e:
                self.is_connected = False
                self.ws_connection = None
                if not self.stop_event.is_set():
                    logger.warning("Agent connection disconnected/failed (%s). Buffering offline...", e)
                    if self.status_callback:
                        self.status_callback("Offline (Buffering)")

                    # Buffer captured frames locally while disconnected
                    self._buffer_offline_frames()

                    await asyncio.sleep(backoff)
                    backoff = min(10.0, backoff * 1.5)

    def _buffer_offline_frames(self):
        """Pushes pending in-memory frames to disk ring buffer."""
        while True:
            try:
                raw_pcm = self.raw_frame_queue.get_nowait()
            except queue.Empty:
                break
            opus_packet = self.audio_encoder.encode(raw_pcm)
            self.seq_num = (self.seq_num + 1) & 0xFFFFFFFF
            self.ring_buffer.push_frame(
                timestamp_ms=int(time.time() * 1000),
                sequence_num=self.seq_num,
                payload=opus_packet
            )

    async def _backfill_worker(self, ws):
        """Gradually transmits offline buffered frames without starving live audio."""
        logger.info("Starting background backfill sync worker...")
        while not self.stop_event.is_set():
            batch = self.ring_buffer.peek_batch(limit=25)
            if not batch:
                await asyncio.sleep(2.0)
                continue

            ids_to_ack = []
            for item in batch:
                row_id, ts_ms, seq, payload = item
                pkt = encode_audio_packet(
                    packet_type=PacketType.AUDIO_BACKFILL,
                    device_id=self.config.device_id,
                    timestamp_ms=ts_ms,
                    sequence_num=seq,
                    payload=payload
                )
                try:
                    await ws.send(pkt)
                    ids_to_ack.append(row_id)
                except Exception:
                    break
                await asyncio.sleep(0.005)  # 5ms yield to ensure live socket never clogs

            if ids_to_ack:
                self.ring_buffer.delete_batch(ids_to_ack)
                logger.debug("Backfilled %d offline frames", len(ids_to_ack))

            await asyncio.sleep(0.05)
