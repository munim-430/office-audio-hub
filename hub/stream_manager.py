"""
Manager Hub Stream Manager & Live Audio Demuxer
Coordinates incoming agent streams, live dashboard broadcasts, and storage ingestion.
"""

import asyncio
import json
import time
import logging
from typing import Dict, Set, Optional, Any
from common.protocol import (
    AudioPacket,
    PacketType,
    decode_audio_packet,
    encode_audio_packet
)
from common.audio_format import AudioDecoder, calculate_rms_level
from hub.storage import ChunkStorageEngine
from hub.pairing import DeviceRegistry

logger = logging.getLogger("StreamManager")

class StreamManager:
    """Manages active live audio streams and real-time dashboard listeners."""
    def __init__(self, storage_engine: ChunkStorageEngine, device_registry: DeviceRegistry):
        self.storage_engine = storage_engine
        self.device_registry = device_registry
        
        # device_id -> active agent websocket
        self.active_agents: Dict[str, Any] = {}
        
        # device_id -> set of dashboard websockets listening to this device
        self.dashboard_subscribers: Dict[str, Set[Any]] = {}
        
        # device_id -> latest audio telemetry (mic_level, last_frame_time, seq)
        self.device_telemetry: Dict[str, Dict[str, Any]] = {}
        
        self.decoder = AudioDecoder()

    def register_agent(self, device_id: str, websocket: Any):
        self.active_agents[device_id] = websocket
        self.device_telemetry[device_id] = {
            "online": True,
            "connected_at": time.time(),
            "last_frame_at": time.time(),
            "mic_level": 0.0,
            "seq": 0
        }
        self.device_registry.update_last_seen(device_id)
        logger.info("Agent connected: %s", device_id)

    def unregister_agent(self, device_id: str):
        if device_id in self.active_agents:
            del self.active_agents[device_id]
        if device_id in self.device_telemetry:
            self.device_telemetry[device_id]["online"] = False
            self.device_telemetry[device_id]["mic_level"] = 0.0
        self.storage_engine.close_device_stream(device_id)
        logger.info("Agent disconnected: %s", device_id)

    def subscribe_dashboard(self, dashboard_ws: Any, device_id: str):
        """Subscribes a dashboard client to listen to a specific device's real-time audio."""
        if device_id not in self.dashboard_subscribers:
            self.dashboard_subscribers[device_id] = set()
        self.dashboard_subscribers[device_id].add(dashboard_ws)
        logger.info("Dashboard client subscribed to live feed of: %s", device_id)

    def unsubscribe_dashboard(self, dashboard_ws: Any, device_id: Optional[str] = None):
        """Unsubscribes a dashboard client from a device (or all devices)."""
        if device_id:
            if device_id in self.dashboard_subscribers:
                self.dashboard_subscribers[device_id].discard(dashboard_ws)
        else:
            for subs in self.dashboard_subscribers.values():
                subs.discard(dashboard_ws)

    async def handle_agent_packet(self, raw_bytes: bytes):
        """Processes an incoming binary packet from an Employee Agent."""
        try:
            packet = decode_audio_packet(raw_bytes)
        except Exception as e:
            logger.warning("Failed to decode agent packet: %s", e)
            return

        device_id = packet.device_id
        now = time.time()

        if packet.packet_type in (PacketType.AUDIO_FRAME, PacketType.AUDIO_BACKFILL):
            # 1. Ingest into 90-minute chunk storage engine
            self.storage_engine.record_frame(
                device_id=device_id,
                timestamp_ms=packet.timestamp_ms,
                seq_num=packet.sequence_num,
                payload=packet.payload
            )

            # 2. Decode PCM for RMS level calculation (and browser audio streaming)
            pcm_data = self.decoder.decode(packet.payload)
            mic_level = calculate_rms_level(pcm_data)

            # Update telemetry
            if device_id in self.device_telemetry:
                self.device_telemetry[device_id]["last_frame_at"] = now
                self.device_telemetry[device_id]["mic_level"] = mic_level
                self.device_telemetry[device_id]["seq"] = packet.sequence_num

            # 3. If live stream packet and dashboard clients are subscribed, broadcast immediately
            if packet.packet_type == PacketType.AUDIO_FRAME:
                subs = self.dashboard_subscribers.get(device_id, set())
                if subs:
                    # Send decoded PCM or framed payload to web dashboard listeners
                    # For Web Audio API, raw 16-bit PCM frames are trivial to play with low latency
                    live_msg = json.dumps({
                        "type": "audio",
                        "device_id": device_id,
                        "timestamp_ms": packet.timestamp_ms,
                        "mic_level": mic_level,
                        "pcm_base64": pcm_data.hex()  # Clean hex/pcm transfer
                    })
                    dead_subs = []
                    for ws in list(subs):
                        try:
                            await ws.send_text(live_msg)
                        except Exception:
                            dead_subs.append(ws)
                    for ds in dead_subs:
                        subs.discard(ds)

        elif packet.packet_type == PacketType.HEARTBEAT_PING:
            if device_id in self.device_telemetry:
                self.device_telemetry[device_id]["last_frame_at"] = now

    def get_devices_status(self) -> List[Dict[str, Any]]:
        """Combines registered device info with live connection telemetry."""
        devices = self.device_registry.list_devices()
        results = []
        now = time.time()
        for dev in devices:
            dev_id = dev["device_id"]
            telemetry = self.device_telemetry.get(dev_id, {})
            is_online = dev_id in self.active_agents
            mic_level = telemetry.get("mic_level", 0.0) if is_online else 0.0
            last_frame_at = telemetry.get("last_frame_at", dev.get("last_seen", 0.0))
            
            results.append({
                "device_id": dev_id,
                "name": dev["name"],
                "hostname": dev.get("hostname", ""),
                "paired_at": dev["paired_at"],
                "is_online": is_online,
                "mic_level": mic_level,
                "last_seen": last_frame_at,
                "active_listeners": len(self.dashboard_subscribers.get(dev_id, set()))
            })
        return results
