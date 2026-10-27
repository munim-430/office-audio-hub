"""
Unit Tests for Manager Hub Storage & Pairing Engines
"""

import time
import pytest
from pathlib import Path
from hub.pairing import DeviceRegistry
from hub.storage import ChunkStorageEngine, ActiveChunkWriter

def test_device_registry_lifecycle(tmp_path):
    db_path = tmp_path / "test_hub.db"
    reg = DeviceRegistry(db_path)

    # 1. Generate pairing code
    code = reg.get_or_create_pairing_code(ttl_seconds=60)
    assert len(code) == 6
    assert reg.get_or_create_pairing_code() == code  # Cached within TTL

    # 2. Pair device
    dev_id = "LAPTOP-DEV-01"
    token = reg.pair_device(code, dev_id, name="Alice Desk", hostname="alice-pc")
    assert token is not None
    assert len(token) == 64

    # 3. Verify token
    assert reg.verify_device_token(dev_id, token) is True
    assert reg.verify_device_token(dev_id, "invalid_token") is False

    # 4. Code should now be consumed
    assert reg.pair_device(code, "LAPTOP-DEV-02", name="Bob Desk") is None

    # 5. List devices
    devices = reg.list_devices()
    assert len(devices) == 1
    assert devices[0]["device_id"] == dev_id
    assert devices[0]["name"] == "Alice Desk"

def test_chunk_recording_and_rotation(tmp_path):
    audio_dir = tmp_path / "audio"
    db_path = tmp_path / "hub.db"

    # Use a tiny chunk duration (0.2 seconds) to test rotation
    engine = ChunkStorageEngine(base_dir=audio_dir, db_path=db_path, chunk_duration_sec=0.2)
    dev_id = "TEST-LAPTOP"

    now_ms = int(time.time() * 1000)
    # Write 5 frames
    for i in range(5):
        engine.record_frame(dev_id, now_ms + i * 20, i, b"\x01\x02\x03\x04" * 10)
    
    # Wait for chunk duration to elapse
    time.sleep(0.3)

    # Write 5 more frames (should trigger rotation to second chunk)
    for i in range(5, 10):
        engine.record_frame(dev_id, now_ms + i * 20, i, b"\x05\x06\x07\x08" * 10)

    engine.close_all()

    # Verify chunks in DB
    chunks = engine.query_chunks(device_id=dev_id)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk["is_finalized"] == 1
        assert Path(chunk["file_path"]).exists()
        assert chunk["frame_count"] > 0

def test_export_chunk_to_wav(tmp_path):
    audio_dir = tmp_path / "audio"
    db_path = tmp_path / "hub.db"
    engine = ChunkStorageEngine(base_dir=audio_dir, db_path=db_path)
    dev_id = "WAV-TEST"

    now_ms = int(time.time() * 1000)
    pcm_payload = b"\x00" * 1920  # 20ms silence
    for i in range(10):
        engine.record_frame(dev_id, now_ms + i * 20, i, pcm_payload)
    engine.close_all()

    chunks = engine.query_chunks(dev_id)
    assert len(chunks) == 1
    chunk_id = chunks[0]["chunk_id"]

    wav_bytes = engine.export_chunk_to_wav_bytes(chunk_id)
    assert wav_bytes is not None
    assert wav_bytes[:4] == b"RIFF"
    assert b"WAVE" in wav_bytes[:12]
