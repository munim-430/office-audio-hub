"""
Binary & JSON Protocol Framing for Office Audio Hub
High-performance framing for 20ms audio frames (50 packets/sec).
"""

import struct
import enum
import time
from typing import NamedTuple, Optional, Tuple
from common.config import MAGIC_HEADER

class PacketType(enum.IntEnum):
    AUDIO_FRAME = 0x01       # Live real-time audio packet (Opus or PCM)
    AUDIO_BACKFILL = 0x02    # Replayed packet from offline ring buffer
    HEARTBEAT_PING = 0x03    # Ping request
    HEARTBEAT_PONG = 0x04    # Pong reply
    AUTH_REQUEST = 0x05      # Initial handshake auth
    AUTH_RESPONSE = 0x06     # Handshake auth reply
    METADATA_UPDATE = 0x07   # Device status/mic level telemetry

class AudioPacket(NamedTuple):
    packet_type: PacketType
    device_id: str
    timestamp_ms: int
    sequence_num: int
    payload: bytes

class ProtocolError(Exception):
    """Raised when parsing an invalid or corrupted packet."""
    pass

def encode_audio_packet(
    packet_type: PacketType,
    device_id: str,
    timestamp_ms: int,
    sequence_num: int,
    payload: bytes
) -> bytes:
    """
    Encodes an AudioPacket into a binary buffer.
    
    Header structure:
      - 1 byte:  MAGIC (0xA0)
      - 1 byte:  Packet Type (uint8)
      - 1 byte:  Device ID length (N, uint8)
      - N bytes: Device ID (utf-8)
      - 8 bytes: Timestamp (uint64, big-endian)
      - 4 bytes: Sequence Number (uint32, big-endian)
      - 2 bytes: Payload length (uint16, big-endian)
      - M bytes: Payload bytes
    """
    dev_bytes = device_id.encode('utf-8')
    dev_len = len(dev_bytes)
    if dev_len > 64:
        dev_bytes = dev_bytes[:64]
        dev_len = 64
        
    payload_len = len(payload)
    if payload_len > 65535:
        raise ValueError(f"Payload length {payload_len} exceeds max uint16 (65535)")
        
    # Pack: MAGIC (B), type (B), dev_len (B), dev_bytes (Ns), timestamp (Q), seq (I), payload_len (H)
    header = struct.pack(
        f">BBB{dev_len}sQIH",
        MAGIC_HEADER,
        int(packet_type),
        dev_len,
        dev_bytes,
        timestamp_ms,
        sequence_num,
        payload_len
    )
    return header + payload

def decode_audio_packet(data: bytes) -> AudioPacket:
    """
    Decodes a binary buffer into an AudioPacket.
    Raises ProtocolError if data is corrupt or too short.
    """
    if len(data) < 17:  # Minimum header with 0-length device_id
        raise ProtocolError(f"Data too short ({len(data)} bytes)")
        
    magic = data[0]
    if magic != MAGIC_HEADER:
        raise ProtocolError(f"Invalid magic header: {hex(magic)} (expected {hex(MAGIC_HEADER)})")
        
    raw_type = data[1]
    try:
        packet_type = PacketType(raw_type)
    except ValueError:
        raise ProtocolError(f"Unknown packet type: {raw_type}")
        
    dev_len = data[2]
    expected_header_len = 1 + 1 + 1 + dev_len + 8 + 4 + 2
    if len(data) < expected_header_len:
        raise ProtocolError(f"Data too short for header with dev_len={dev_len}")
        
    dev_bytes = data[3 : 3 + dev_len]
    device_id = dev_bytes.decode('utf-8', errors='replace')
    
    offset = 3 + dev_len
    timestamp_ms, sequence_num, payload_len = struct.unpack(">QIH", data[offset : offset + 14])
    
    offset += 14
    payload = data[offset : offset + payload_len]
    if len(payload) != payload_len:
        raise ProtocolError(f"Payload truncated: expected {payload_len} bytes, got {len(payload)}")
        
    return AudioPacket(
        packet_type=packet_type,
        device_id=device_id,
        timestamp_ms=timestamp_ms,
        sequence_num=sequence_num,
        payload=payload
    )

def create_heartbeat_ping(device_id: str, seq: int) -> bytes:
    """Generates a binary heartbeat ping packet."""
    return encode_audio_packet(
        packet_type=PacketType.HEARTBEAT_PING,
        device_id=device_id,
        timestamp_ms=int(time.time() * 1000),
        sequence_num=seq,
        payload=b""
    )

def create_heartbeat_pong(device_id: str, seq: int) -> bytes:
    """Generates a binary heartbeat pong packet."""
    return encode_audio_packet(
        packet_type=PacketType.HEARTBEAT_PONG,
        device_id=device_id,
        timestamp_ms=int(time.time() * 1000),
        sequence_num=seq,
        payload=b""
    )
