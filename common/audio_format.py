"""
Audio Encoding, Decoding, and Level Metering Utilities
Wraps opuslib for voice-optimized Opus with transparent fallback.
"""

import math
import struct
import logging
from typing import Optional

logger = logging.getLogger("AudioFormat")

try:
    import opuslib
    OPUS_AVAILABLE = True
except (ImportError, Exception) as exc:
    OPUS_AVAILABLE = False
    logger.warning("opuslib not available (%s); operating in raw PCM mode", exc)

from common.config import SAMPLE_RATE, CHANNELS, FRAME_DURATION_MS, SAMPLES_PER_FRAME

class AudioEncoder:
    """Encodes 20ms 48kHz mono 16-bit PCM frames into compressed Opus packets."""
    def __init__(self, sample_rate: int = SAMPLE_RATE, channels: int = CHANNELS):
        self.sample_rate = sample_rate
        self.channels = channels
        self._encoder = None
        if OPUS_AVAILABLE:
            try:
                self._encoder = opuslib.Encoder(
                    sample_rate,
                    channels,
                    opuslib.APPLICATION_VOIP
                )
                logger.info("OpusEncoder initialized at %d Hz, %d ch (VOIP)", sample_rate, channels)
            except Exception as e:
                logger.error("Failed to initialize OpusEncoder: %s", e)
                self._encoder = None

    def encode(self, pcm_bytes: bytes) -> bytes:
        """Encodes raw PCM bytes to Opus packet (or passes through if Opus unavailable)."""
        if self._encoder is not None:
            try:
                return self._encoder.encode(pcm_bytes, SAMPLES_PER_FRAME)
            except Exception as e:
                logger.error("Opus encode error: %s", e)
                return pcm_bytes
        return pcm_bytes

class AudioDecoder:
    """Decodes Opus packets back into 20ms 48kHz mono 16-bit PCM frames."""
    def __init__(self, sample_rate: int = SAMPLE_RATE, channels: int = CHANNELS):
        self.sample_rate = sample_rate
        self.channels = channels
        self._decoder = None
        if OPUS_AVAILABLE:
            try:
                self._decoder = opuslib.Decoder(sample_rate, channels)
            except Exception as e:
                logger.error("Failed to initialize OpusDecoder: %s", e)
                self._decoder = None

    def decode(self, opus_bytes: bytes) -> bytes:
        """Decodes Opus packet to PCM bytes (or passes through if uncompressed)."""
        if self._decoder is not None and len(opus_bytes) < SAMPLES_PER_FRAME * 2:
            try:
                return self._decoder.decode(opus_bytes, SAMPLES_PER_FRAME)
            except Exception as e:
                logger.error("Opus decode error: %s", e)
                return opus_bytes
        return opus_bytes

def calculate_rms_level(pcm_bytes: bytes) -> float:
    """
    Calculates RMS volume level from 16-bit PCM (normalized 0.0 to 1.0).
    Useful for live dashboard microphone level meters.
    """
    if not pcm_bytes or len(pcm_bytes) < 2:
        return 0.0
    count = len(pcm_bytes) // 2
    try:
        shorts = struct.unpack(f"{count}h", pcm_bytes[:count * 2])
        sum_squares = sum(s * s for s in shorts)
        rms = math.sqrt(sum_squares / count)
        # 32768 is max int16
        normalized = min(1.0, rms / 32768.0)
        return round(normalized, 3)
    except Exception:
        return 0.0
