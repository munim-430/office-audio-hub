"""
Unit Tests for Employee Agent Offline Ring Buffer
"""

import time
import pytest
from pathlib import Path
from agent.ring_buffer import OfflineRingBuffer

def test_ring_buffer_push_and_peek(tmp_path):
    db_file = tmp_path / "test_cache.db"
    buf = OfflineRingBuffer(db_path=db_file)

    assert buf.get_pending_count() == 0

    # Push 10 frames
    now_ms = int(time.time() * 1000)
    for i in range(10):
        buf.push_frame(now_ms + i * 20, i, f"frame-{i}".encode("utf-8"))

    assert buf.get_pending_count() == 10

    # Peek batch of 4
    batch1 = buf.peek_batch(limit=4)
    assert len(batch1) == 4
    assert batch1[0][2] == 0  # sequence 0
    assert batch1[0][3] == b"frame-0"

    # Delete first batch
    buf.delete_batch([item[0] for item in batch1])
    assert buf.get_pending_count() == 6

    # Peek remaining
    batch2 = buf.peek_batch(limit=10)
    assert len(batch2) == 6
    assert batch2[0][2] == 4  # sequence 4

    # Delete all
    buf.delete_batch([item[0] for item in batch2])
    assert buf.get_pending_count() == 0

def test_ring_buffer_retention_purge(tmp_path):
    db_file = tmp_path / "test_retention.db"
    # Set retention to 0 hours (expires immediately)
    buf = OfflineRingBuffer(db_path=db_file, max_hours=0)

    buf.push_frame(1000, 1, b"old-frame")
    time.sleep(0.05)
    buf._enforce_capacity()

    assert buf.get_pending_count() == 0
