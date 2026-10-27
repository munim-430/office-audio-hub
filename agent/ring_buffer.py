"""
Employee Agent Local Offline Ring Buffer
Caches audio frames during network outages (up to 3 days / 2 GB) with FIFO eviction
and background backfill synchronization that never starves the live stream.
"""

import sqlite3
import time
import logging
from pathlib import Path
from typing import List, Tuple, Optional
from common.config import MAX_OFFLINE_BUFFER_BYTES, MAX_OFFLINE_RETENTION_HOURS

logger = logging.getLogger("OfflineRingBuffer")

class OfflineRingBuffer:
    """SQLite-backed persistent FIFO ring buffer for offline audio frames."""
    def __init__(
        self,
        db_path: Path = Path("agent_cache.db"),
        max_bytes: int = MAX_OFFLINE_BUFFER_BYTES,
        max_hours: int = MAX_OFFLINE_RETENTION_HOURS
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.max_age_seconds = max_hours * 3600
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS offline_frames (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_ms INTEGER NOT NULL,
                    sequence_num INTEGER NOT NULL,
                    payload BLOB NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_offline_ts ON offline_frames(timestamp_ms)")
            conn.commit()

    def push_frame(self, timestamp_ms: int, sequence_num: int, payload: bytes):
        """Pushes an audio frame to the offline buffer and enforces ring capacity."""
        now = time.time()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO offline_frames (timestamp_ms, sequence_num, payload, created_at)
                VALUES (?, ?, ?, ?)
            """, (timestamp_ms, sequence_num, payload, now))
            conn.commit()

        # Enforce size and retention limit every 100 frames or opportunistically
        if sequence_num % 100 == 0:
            self._enforce_capacity()

    def _enforce_capacity(self):
        """Purges frames exceeding age limit or max disk bytes."""
        now = time.time()
        cutoff = now - self.max_age_seconds

        with self._get_connection() as conn:
            # 1. Purge older than retention window
            conn.execute("DELETE FROM offline_frames WHERE created_at < ?", (cutoff,))

            # 2. Check file size
            if self.db_path.exists():
                size = self.db_path.stat().st_size
                if size > self.max_bytes:
                    # Delete oldest 20% of rows to return under quota
                    logger.warning("Offline buffer size (%d bytes) exceeds quota (%d bytes); trimming oldest records.",
                                   size, self.max_bytes)
                    conn.execute("""
                        DELETE FROM offline_frames WHERE id IN (
                            SELECT id FROM offline_frames ORDER BY id ASC LIMIT (
                                SELECT count(*) / 5 FROM offline_frames
                            )
                        )
                    """)
            conn.commit()

    def peek_batch(self, limit: int = 50) -> List[Tuple[int, int, int, bytes]]:
        """
        Retrieves a batch of un-synced frames in chronological order.
        Returns [(id, timestamp_ms, sequence_num, payload), ...]
        """
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT id, timestamp_ms, sequence_num, payload
                FROM offline_frames
                ORDER BY id ASC
                LIMIT ?
            """, (limit,))
            return [(row["id"], row["timestamp_ms"], row["sequence_num"], row["payload"]) for row in cursor.fetchall()]

    def delete_batch(self, ids: List[int]):
        """Deletes successfully backfilled frames from the buffer."""
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self._get_connection() as conn:
            conn.execute(f"DELETE FROM offline_frames WHERE id IN ({placeholders})", ids)
            conn.commit()

    def get_pending_count(self) -> int:
        """Returns the number of pending frames waiting to backfill."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT count(*) as cnt FROM offline_frames")
            row = cursor.fetchone()
            return row["cnt"] if row else 0

    def clear(self):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM offline_frames")
            conn.commit()
