"""Live audio capture with VAD-based speech segmentation.

Captures 16kHz mono audio from the default input device, runs WebRTC VAD
to detect speech vs silence, and yields speech segments as numpy float32
arrays ready for Whisper transcription.
"""
from __future__ import annotations

import collections
import queue
import threading
import time
from typing import Optional

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "float32"
BLOCK_SIZE = 480  # 30ms at 16kHz — required by webrtcvad (10/20/30 ms frames)

# Frame size for webrtcvad at 16kHz: must be 10/20/30 ms.
# 30ms = 480 samples. Use that.
VAD_FRAME_MS = 30
VAD_FRAME_SAMPLES = int(SAMPLE_RATE * VAD_FRAME_MS / 1000)

MAX_SEGMENT_SEC = 10.0  # force-yield a segment after this much continuous speech
MIN_SEGMENT_SEC = 0.5   # discard segments shorter than this (blips/coughs)


class AudioCapture:
    """Live mic capture with WebRTC VAD. Yields speech segments as float32 arrays."""

    def __init__(
        self,
        vad_aggressiveness: int = 2,
        device: Optional[int] = None,
    ):
        """vad_aggressiveness: 0-3, higher = more aggressive (filters more)."""
        self.vad_aggressiveness = vad_aggressiveness
        self.device = device
        self._audio_q: "queue.Queue[np.ndarray]" = queue.Queue()
        self._stream: Optional[sd.InputStream] = None
        self._vad = None
        self._running = False
        self._overflow = False

    def _load_vad(self):
        if self._vad is not None:
            return
        try:
            import webrtcvad
        except ImportError as e:
            raise ImportError(
                "webrtcvad is required. Install with: pip install webrtcvad"
            ) from e
        self._vad = webrtcvad.Vad(self.vad_aggressiveness)

    def _callback(self, indata, frames, time_info, status):
        if status:
            self._overflow = True
        # Mono float32
        chunk = indata.copy().reshape(-1)
        self._audio_q.put(chunk)

    def _is_speech(self, pcm_int16: np.ndarray) -> bool:
        """Run VAD on a single frame (must be 30ms = 480 samples at 16kHz)."""
        return self._vad.is_speech(pcm_int16.tobytes(), SAMPLE_RATE)

    def segments(self):
        """Generator yielding speech segments as float32 numpy arrays at 16kHz."""
        self._load_vad()
        self._running = True
        self._audio_q = queue.Queue()
        self._overflow = False

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=VAD_FRAME_SAMPLES,
            callback=self._callback,
            device=self.device,
        )
        self._stream.start()

        speech_active = False
        speech_samples: list = []
        silence_count = 0

        try:
            while self._running:
                try:
                    chunk = self._audio_q.get(timeout=0.1)
                except queue.Empty:
                    continue

                # Convert to int16 for VAD
                pcm = np.clip(chunk * 32767, -32768, 32767).astype(np.int16)
                is_speech = self._is_speech(pcm)

                if is_speech and not speech_active:
                    speech_active = True
                    speech_samples = [chunk]
                    silence_count = 0
                elif is_speech and speech_active:
                    speech_samples.append(chunk)
                    silence_count = 0
                    dur = len(speech_samples) * VAD_FRAME_MS / 1000.0
                    if dur >= MAX_SEGMENT_SEC:
                        seg = np.concatenate(speech_samples)
                        if len(seg) / SAMPLE_RATE >= MIN_SEGMENT_SEC:
                            yield seg
                        speech_samples = []
                        speech_active = False
                elif not is_speech and speech_active:
                    speech_samples.append(chunk)
                    silence_count += 1
                    if silence_count >= 5:
                        trim = min(silence_count, len(speech_samples))
                        seg = np.concatenate(speech_samples[:-trim]) if trim < len(speech_samples) else np.array([], dtype=np.float32)
                        if len(seg) / SAMPLE_RATE >= MIN_SEGMENT_SEC:
                            yield seg
                        speech_samples = []
                        speech_active = False
                        silence_count = 0
                else:
                    silence_count = 0
        finally:
            self._stream.stop()
            self._stream.close()
            if speech_samples and speech_active:
                trim = min(silence_count, len(speech_samples))
                seg = np.concatenate(speech_samples[:-trim]) if trim < len(speech_samples) else np.array([], dtype=np.float32)
                if len(seg) / SAMPLE_RATE >= MIN_SEGMENT_SEC:
                    yield seg

    def stop(self):
        self._running = False

    @property
    def had_overflow(self) -> bool:
        return self._overflow
