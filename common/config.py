"""
Shared Configuration Constants for Office Audio Hub & Streamer
"""

import os
from pathlib import Path

# Networking
DEFAULT_HUB_PORT = 8080
DEFAULT_HUB_HOST = "0.0.0.0"
WS_AUDIO_STREAM_PATH = "/ws/agent"
WS_DASHBOARD_PATH = "/ws/dashboard"

# Audio Framing & Opus Specs
SAMPLE_RATE = 48000          # Opus native frequency
CHANNELS = 1                 # Mono voice
FRAME_DURATION_MS = 20       # 20ms frame
SAMPLES_PER_FRAME = int(SAMPLE_RATE * (FRAME_DURATION_MS / 1000.0))  # 960 samples
BYTES_PER_SAMPLE = 2         # 16-bit PCM (int16)
FRAME_BYTES = SAMPLES_PER_FRAME * CHANNELS * BYTES_PER_SAMPLE        # 1920 bytes

# Recording & Storage Specs
CHUNK_DURATION_MINUTES = 90  # 90-minute audio chunks
CHUNK_DURATION_SECONDS = CHUNK_DURATION_MINUTES * 60  # 5400 seconds
EXPECTED_FRAMES_PER_CHUNK = int(CHUNK_DURATION_SECONDS / (FRAME_DURATION_MS / 1000.0))  # 270,000 frames

# Offline Ring Buffer (Employee Agent)
MAX_OFFLINE_BUFFER_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB limit
MAX_OFFLINE_RETENTION_HOURS = 72                    # 3 days limit

# Protocol Magic Header
MAGIC_HEADER = 0xA0

# Default Storage Root
DEFAULT_STORAGE_DIR = Path("storage")
DEFAULT_AUDIO_DIR = DEFAULT_STORAGE_DIR / "audio"
DEFAULT_DB_FILE = DEFAULT_STORAGE_DIR / "hub.db"
