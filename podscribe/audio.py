"""Live audio capture with VAD-based speech segmentation.

Captures 16kHz mono audio from the default input device, runs WebRTC VAD
to detect speech vs silence, and yields speech segments as numpy float32
arrays ready for Whisper transcription.
"""
from __future__ import annotations

import collections
import queue
import sys
import threading
import time
from typing import Optional

import numpy as np

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
        on_level=lambda f: None,
    ):
        """vad_aggressiveness: 0-3, higher = more aggressive (filters more).
        on_level: called with float RMS in [0.0, 1.0] for each audio chunk.
        """
        self.vad_aggressiveness = vad_aggressiveness
        self.device = device
        self._on_level = on_level
        self._audio_q: "queue.Queue[np.ndarray]" = queue.Queue()
        self._stream: Optional[sd.InputStream] = None
        self._vad = None
        self._running = False
        self._overflow = False
        if device is not None:
            self._probe_device(device)

    def _probe_device(self, device: int) -> None:
        """Validate the input device index eagerly and raise an actionable error.

        Imported sd lazily so the common (device=None) path pays no cost —
        see R-5. On a bad index PortAudio would otherwise surface a raw
        traceback from sd.InputStream.start() during segments().
        """
        try:
            import sounddevice as sd
            info = sd.query_devices(device, "input")
        except (ValueError, IndexError, sd.PortAudioError) as e:
            raise ValueError(
                f"no input device at index {device}. "
                f"Run 'podscribe list-devices' to see valid indices. ({e})"
            ) from e
        if not info or (info.get("max_input_channels", 0) or 0) < 1:
            raise ValueError(
                f"device at index {device} has no input channels. "
                f"Run 'podscribe list-devices' to see valid input devices."
            )

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
        chunk = indata.copy().reshape(-1)
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        self._on_level(min(1.0, rms))
        self._audio_q.put(chunk)

    def _is_speech(self, pcm_int16: np.ndarray) -> bool:
        """Run VAD on a single frame (must be 30ms = 480 samples at 16kHz)."""
        return self._vad.is_speech(pcm_int16.tobytes(), SAMPLE_RATE)

    def segments(self):
        """Generator yielding speech segments as float32 numpy arrays at 16kHz."""
        import sounddevice as sd  # lazy: only loaded when recording starts
        self._load_vad()
        self._running = True
        self._audio_q = queue.Queue()
        self._overflow = False

        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=VAD_FRAME_SAMPLES,
                callback=self._callback,
                device=self.device,
            )
            self._stream.start()
        except sd.PortAudioError as e:
            sys.stderr.write(
                f"audio input failed: {e}. "
                f"Check mic permissions / device availability "
                f"(run 'podscribe list-devices').\n"
            )
            sys.stderr.flush()
            return

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
                        seg = np.concatenate(speech_samples[:len(speech_samples)-trim]) if trim < len(speech_samples) else np.array([], dtype=np.float32)
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
                seg = np.concatenate(speech_samples[:len(speech_samples)-trim]) if trim < len(speech_samples) else np.array([], dtype=np.float32)
                if len(seg) / SAMPLE_RATE >= MIN_SEGMENT_SEC:
                    yield seg

    def stop(self):
        self._running = False

    @property
    def had_overflow(self) -> bool:
        return self._overflow
