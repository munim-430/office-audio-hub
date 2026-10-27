"""
Unit Tests for Audio Framing Protocol
"""

import time
import pytest
from common.protocol import (
    PacketType,
    AudioPacket,
    encode_audio_packet,
    decode_audio_packet,
    create_heartbeat_ping,
    create_heartbeat_pong,
    ProtocolError
)

def test_encode_decode_audio_frame():
    dev_id = "DESK-ALICE-WIN11"
    now_ms = int(time.time() * 1000)
    seq = 42
    payload = b"\x12\x34\x56\x78" * 15  # 60 bytes Opus packet

    encoded = encode_audio_packet(
        packet_type=PacketType.AUDIO_FRAME,
        device_id=dev_id,
        timestamp_ms=now_ms,
        sequence_num=seq,
        payload=payload
    )

    decoded = decode_audio_packet(encoded)
    assert decoded.packet_type == PacketType.AUDIO_FRAME
    assert decoded.device_id == dev_id
    assert decoded.timestamp_ms == now_ms
    assert decoded.sequence_num == seq
    assert decoded.payload == payload

def test_heartbeat_ping_pong():
    dev_id = "DESK-BOB"
    ping_bytes = create_heartbeat_ping(dev_id, 101)
    decoded_ping = decode_audio_packet(ping_bytes)
    assert decoded_ping.packet_type == PacketType.HEARTBEAT_PING
    assert decoded_ping.device_id == dev_id
    assert decoded_ping.sequence_num == 101
    assert decoded_ping.payload == b""

    pong_bytes = create_heartbeat_pong(dev_id, 101)
    decoded_pong = decode_audio_packet(pong_bytes)
    assert decoded_pong.packet_type == PacketType.HEARTBEAT_PONG
    assert decoded_pong.device_id == dev_id

def test_invalid_magic_header():
    bad_bytes = b"\xFF\x01\x05agent" + b"\x00" * 20
    with pytest.raises(ProtocolError, match="Invalid magic header"):
        decode_audio_packet(bad_bytes)

def test_truncated_data():
    with pytest.raises(ProtocolError, match="Data too short"):
        decode_audio_packet(b"\xA0\x01")

def test_long_device_id_truncation():
    super_long_id = "A" * 100
    encoded = encode_audio_packet(
        packet_type=PacketType.AUDIO_FRAME,
        device_id=super_long_id,
        timestamp_ms=1000,
        sequence_num=1,
        payload=b"abc"
    )
    decoded = decode_audio_packet(encoded)
    assert len(decoded.device_id) == 64
    assert decoded.device_id == "A" * 64
