"""
Resilient Audio Capture Engine for Employee Agent
Wraps sounddevice PortAudio with a WASAPI Lifecycle Supervisor Loop.
Includes automatic fallback/mock mode for test environments.
"""

import time
import queue
import logging
import threading
from typing import Optional, Callable
from common.config import SAMPLE_RATE, CHANNELS, FRAME_DURATION_MS, SAMPLES_PER_FRAME

logger = logging.getLogger("AudioCapture")

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except (ImportError, Exception) as exc:
    SOUNDDEVICE_AVAILABLE = False
    logger.warning("sounddevice not available (%s); mock capture mode active", exc)

class AudioCaptureSupervisor:
    """
    Manages continuous 24/7 audio capture. Detects hardware invalidations
    (device unplugging, modern standby sleep/wake) and cleanly re-acquires default audio input.
    """
    def __init__(self, on_frame_captured: Callable[[bytes], None], test_mode: bool = False):
        self.on_frame_captured = on_frame_captured
        self.test_mode = test_mode or not SOUNDDEVICE_AVAILABLE
        self.stop_event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None
        self.stream = None

    def start(self):
        self.stop_event.clear()
        if self.test_mode:
            self.worker_thread = threading.Thread(target=self._run_mock_loop, daemon=True)
        else:
            self.worker_thread = threading.Thread(target=self._run_portaudio_supervisor, daemon=True)
        self.worker_thread.start()
        logger.info("Audio capture supervisor started (test_mode=%s)", self.test_mode)

    def stop(self):
        self.stop_event.set()
        if self.stream:
            try:
                self.stream.abort()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2.0)
        logger.info("Audio capture supervisor stopped")

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.warning("PortAudio status: %s", status)
        raw_pcm = indata.tobytes()
        self.on_frame_captured(raw_pcm)

    def _run_portaudio_supervisor(self):
        while not self.stop_event.is_set():
            try:
                # 1. Reset PortAudio device cache to detect new default microphones
                try:
                    sd._terminate()
                    sd._initialize()
                except Exception as e:
                    logger.debug("PortAudio re-init exception: %s", e)

                # 2. Acquire default capture endpoint
                device_info = sd.query_devices(kind='input')
                logger.info("Acquiring default input device: %s", device_info.get("name"))

                # 3. Open capture stream with 20ms blocksize (960 samples @ 48kHz)
                self.stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    blocksize=SAMPLES_PER_FRAME,
                    channels=CHANNELS,
                    dtype='int16',
                    callback=self._audio_callback
                )

                with self.stream:
                    logger.info("PortAudio InputStream active.")
                    while not self.stop_event.is_set():
                        if not self.stream.active:
                            logger.warning("PortAudio stream stopped unexpectedly")
                            break
                        time.sleep(0.5)

            except Exception as e:
                logger.error("Audio capture error (re-acquiring in 2s): %s", e)
            finally:
                if self.stream:
                    try:
                        self.stream.abort()
                        self.stream.close()
                    except Exception:
                        pass
                    self.stream = None

            if not self.stop_event.is_set():
                time.sleep(2.0)

    def _run_mock_loop(self):
        """Simulates 20ms audio frames (for headless testing or missing hardware)."""
        logger.info("Running synthetic mock audio capture pump (20ms intervals)")
        frame_bytes = b"\x00" * (SAMPLES_PER_FRAME * 2)
        interval = FRAME_DURATION_MS / 1000.0  # 0.02s
        while not self.stop_event.is_set():
            start_t = time.time()
            self.on_frame_captured(frame_bytes)
            elapsed = time.time() - start_t
            sleep_time = max(0.0, interval - elapsed)
            time.sleep(sleep_time)
