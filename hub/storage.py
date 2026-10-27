"""
Manager Hub 90-Minute Audio Chunk Storage Engine
Assembles incoming continuous audio frames into corruption-resistant 90-minute files on local disk.
"""

import os
import io
import time
import struct
import wave
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Any
from common.config import (
    DEFAULT_STORAGE_DIR,
    DEFAULT_AUDIO_DIR,
    DEFAULT_DB_FILE,
    CHUNK_DURATION_SECONDS,
    SAMPLE_RATE,
    CHANNELS,
    SAMPLES_PER_FRAME
)
from common.audio_format import AudioDecoder

logger = logging.getLogger("HubStorage")

# Chunk framing format:
# Each frame on disk:
# [uint16 payload_len][uint64 timestamp_ms][uint32 sequence_num][payload bytes]
FRAME_RECORD_HEADER_FORMAT = ">HQI"
FRAME_RECORD_HEADER_SIZE = struct.calcsize(FRAME_RECORD_HEADER_FORMAT)  # 2 + 8 + 4 = 14 bytes

class ActiveChunkWriter:
    """Manages an active writing stream for a specific device."""
    def __init__(self, device_id: str, base_dir: Path, db_path: Path, max_duration_sec: float = CHUNK_DURATION_SECONDS):
        self.device_id = device_id
        self.base_dir = Path(base_dir)
        self.db_path = Path(db_path)
        self.max_duration_sec = max_duration_sec
        
        self.current_chunk_id: Optional[str] = None
        self.file_handle: Optional[io.BufferedWriter] = None
        self.current_file_path: Optional[Path] = None
        self.start_time: float = 0.0
        self.last_frame_time: float = 0.0
        self.frame_count: int = 0
        self.bytes_written: int = 0

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _start_new_chunk(self, frame_timestamp_ms: int):
        self.finalize_current_chunk()

        now = time.time()
        self.start_time = now
        self.last_frame_time = now
        self.frame_count = 0
        self.bytes_written = 0

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        time_str = datetime.now(timezone.utc).strftime("%H-%M-%S") + f"_{int(now * 1000) % 1000:03d}"
        self.current_chunk_id = f"{self.device_id}_{date_str}_{time_str}"
        
        target_dir = self.base_dir / self.device_id / date_str
        target_dir.mkdir(parents=True, exist_ok=True)
        
        self.current_file_path = target_dir / f"{self.current_chunk_id}.opus.part"
        self.file_handle = open(self.current_file_path, "wb")

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO chunks (
                    chunk_id, device_id, date_str, start_time, end_time,
                    duration_seconds, frame_count, file_path, file_size_bytes, is_finalized
                ) VALUES (?, ?, ?, ?, ?, 0.0, 0, ?, 0, 0)
                ON CONFLICT(chunk_id) DO UPDATE SET file_path = excluded.file_path
            """, (self.current_chunk_id, self.device_id, date_str, now, now, str(self.current_file_path)))
            conn.commit()

        logger.info("Started new 90-min chunk: %s", self.current_file_path)

    def write_frame(self, timestamp_ms: int, seq_num: int, payload: bytes):
        """Writes an incoming audio frame. Automatically rotates when 90 minutes elapse."""
        now = time.time()
        if self.file_handle is None:
            self._start_new_chunk(timestamp_ms)
        elif (now - self.start_time) >= self.max_duration_sec:
            logger.info("90 minutes elapsed for device %s; rotating chunk.", self.device_id)
            self._start_new_chunk(timestamp_ms)

        # Write frame record header + payload
        header = struct.pack(FRAME_RECORD_HEADER_FORMAT, len(payload), timestamp_ms, seq_num)
        self.file_handle.write(header)
        self.file_handle.write(payload)
        self.file_handle.flush()

        self.frame_count += 1
        self.bytes_written += len(header) + len(payload)
        self.last_frame_time = now

    def finalize_current_chunk(self):
        """Closes and finalizes the active chunk file."""
        if self.file_handle is not None:
            try:
                self.file_handle.flush()
                self.file_handle.close()
            except Exception as e:
                logger.error("Error closing chunk file: %s", e)
            self.file_handle = None

        if self.current_file_path and self.current_file_path.exists():
            final_path = self.current_file_path.with_suffix("").with_suffix(".opus")
            try:
                self.current_file_path.rename(final_path)
                self.current_file_path = final_path
            except Exception as e:
                logger.error("Error renaming finalized chunk file: %s", e)

            duration = max(0.0, self.last_frame_time - self.start_time)
            file_size = final_path.stat().st_size if final_path.exists() else self.bytes_written

            with self._get_connection() as conn:
                conn.execute("""
                    UPDATE chunks SET
                        end_time = ?,
                        duration_seconds = ?,
                        frame_count = ?,
                        file_path = ?,
                        file_size_bytes = ?,
                        is_finalized = 1
                    WHERE chunk_id = ?
                """, (self.last_frame_time, duration, self.frame_count, str(self.current_file_path), file_size, self.current_chunk_id))
                conn.commit()

            logger.info("Finalized chunk %s (duration: %.1fs, frames: %d, size: %d bytes)",
                        self.current_chunk_id, duration, self.frame_count, file_size)

        self.current_chunk_id = None
        self.current_file_path = None


class ChunkStorageEngine:
    """Coordinates chunk recording, query indexing, and audio export across all devices."""
    def __init__(self, base_dir: Path = DEFAULT_AUDIO_DIR, db_path: Path = DEFAULT_DB_FILE, chunk_duration_sec: float = CHUNK_DURATION_SECONDS):
        self.base_dir = Path(base_dir)
        self.db_path = Path(db_path)
        self.chunk_duration_sec = chunk_duration_sec
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.writers: Dict[str, ActiveChunkWriter] = {}

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    date_str TEXT NOT NULL,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    duration_seconds REAL NOT NULL,
                    frame_count INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    file_size_bytes INTEGER NOT NULL,
                    is_finalized INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_dev_date ON chunks(device_id, date_str)")
            conn.commit()

    def get_writer(self, device_id: str) -> ActiveChunkWriter:
        if device_id not in self.writers:
            self.writers[device_id] = ActiveChunkWriter(
                device_id=device_id,
                base_dir=self.base_dir,
                db_path=self.db_path,
                max_duration_sec=self.chunk_duration_sec
            )
        return self.writers[device_id]

    def record_frame(self, device_id: str, timestamp_ms: int, seq_num: int, payload: bytes):
        """Records an audio frame for the given device."""
        writer = self.get_writer(device_id)
        writer.write_frame(timestamp_ms, seq_num, payload)

    def close_device_stream(self, device_id: str):
        if device_id in self.writers:
            self.writers[device_id].finalize_current_chunk()
            del self.writers[device_id]

    def close_all(self):
        for dev_id in list(self.writers.keys()):
            self.close_device_stream(dev_id)

    def query_chunks(self, device_id: Optional[str] = None, date_str: Optional[str] = None) -> List[Dict[str, Any]]:
        """Queries recorded chunks from the index."""
        query = "SELECT * FROM chunks WHERE 1=1"
        params = []
        if device_id:
            query += " AND device_id = ?"
            params.append(device_id)
        if date_str:
            query += " AND date_str = ?"
            params.append(date_str)
        query += " ORDER BY start_time DESC"

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_chunk(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def read_frames_from_file(file_path: Path) -> List[bytes]:
        """Reads all payload frames from a chunk file."""
        frames = []
        path = Path(file_path)
        if not path.exists():
            return frames
        with open(path, "rb") as f:
            while True:
                hdr = f.read(FRAME_RECORD_HEADER_SIZE)
                if len(hdr) < FRAME_RECORD_HEADER_SIZE:
                    break
                payload_len, ts, seq = struct.unpack(FRAME_RECORD_HEADER_FORMAT, hdr)
                payload = f.read(payload_len)
                if len(payload) < payload_len:
                    break
                frames.append(payload)
        return frames

    def export_chunk_to_wav_bytes(self, chunk_id: str) -> Optional[bytes]:
        """
        Decodes a chunk's Opus/PCM frames and renders a standard WAV byte stream
        for seamless in-browser playback or download.
        """
        chunk = self.get_chunk(chunk_id)
        if not chunk:
            return None
        file_path = Path(chunk["file_path"])
        if not file_path.exists():
            return None

        frames = self.read_frames_from_file(file_path)
        decoder = AudioDecoder(SAMPLE_RATE, CHANNELS)
        
        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wav_file:
            wav_file.setnchannels(CHANNELS)
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(SAMPLE_RATE)
            for frame in frames:
                pcm_data = decoder.decode(frame)
                wav_file.writeframes(pcm_data)

        return wav_io.getvalue()
