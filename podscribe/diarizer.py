"""Speaker diarization via pyannote.audio (post-hoc, lazy-loaded).

Heavy imports (pyannote.audio, torch, torchaudio) are deferred inside method bodies
so a default `pip install -e .` stays light; a missing install raises ImportError
with a clear message, never a crash mid-run.
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


_TRANSCRIPT_LINE_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\]\s*(.*)$")


@dataclass
class Utterance:
    start_sec: float
    end_sec: float
    speaker: int          # 0..N-1, renumbered by first appearance
    text: str             # verbatim from the original transcript line


def _fmt_time(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class Diarizer:
    """pyannote.audio speaker-diarization-3.1 wrapper. Pipeline cached on the instance."""

    def __init__(
        self,
        hf_token: str,
        *,
        use_mps: bool = False,
        num_speakers: Optional[int] = None,
    ):
        self.hf_token = hf_token
        self.use_mps = use_mps
        self.num_speakers = num_speakers
        self._pipeline = None

    @staticmethod
    def write_diarized_transcript(
        orig_md: Path, utterances: List[Utterance], out_path: Path,
    ) -> None:
        """Emit .diarized.md: header up to '## Transcript', then one line per utterance.

        Atomic write via tempfile.mkstemp + os.replace. Either the complete file
        appears at out_path, or out_path stays absent.
        """
        orig_text = orig_md.read_text()
        if "## Transcript" in orig_text:
            header, _ = orig_text.split("## Transcript", 1)
            header = header + "## Transcript\n\n"
        else:
            header = orig_text + "\n## Transcript\n\n"
        body_lines = [
            f"[{_fmt_time(u.start_sec)}] Speaker {u.speaker}: {u.text.strip()}"
            for u in utterances
        ]
        new_text = header + "\n".join(body_lines) + "\n"

        out_dir = out_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=out_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(new_text)
            os.replace(tmp_path, out_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _parse_transcript_lines(md_path: Path) -> List[Tuple[float, str]]:
        """Return [(start_sec, text)] per [HH:MM:SS] line; non-matching lines skipped."""
        out: List[Tuple[float, str]] = []
        for line in md_path.read_text().splitlines():
            m = _TRANSCRIPT_LINE_RE.match(line)
            if not m:
                continue
            h, mn, s, text = m.groups()
            start = int(h) * 3600 + int(mn) * 60 + int(s)
            out.append((float(start), text))
        return out

    @staticmethod
    def _snap_turns_to_lines(
        turns: List[Tuple[float, float, int]], line_start_secs: List[float],
    ) -> List[Optional[int]]:
        """Per line, the covering turn's raw speaker (latest start wins); None if uncovered."""
        out: List[Optional[int]] = []
        for t in line_start_secs:
            best: Optional[int] = None
            best_start = -1.0
            for start, end, speaker in turns:
                if start <= t < end and start > best_start:
                    best_start = start
                    best = speaker
            out.append(best)
        return out

    @staticmethod
    def _renumber_speakers(raw_labels: List[Optional[int]]) -> List[int]:
        """Map raw pyannote indices to 0..N-1 by first appearance; None → nearest preceding (0 first)."""
        out: List[int] = []
        mapping: dict = {}
        next_label = 0
        last_emitted = 0
        for raw in raw_labels:
            if raw is None:
                out.append(last_emitted)
                continue
            if raw not in mapping:
                mapping[raw] = next_label
                next_label += 1
            last_emitted = mapping[raw]
            out.append(last_emitted)
        return out

    def diarize(self, audio_path: Path, transcript_md_path: Path) -> List[Utterance]:
        """Run pyannote on continuous .raw; snap turns to lines; renumber speakers."""
        lines = self._parse_transcript_lines(transcript_md_path)
        if not lines:
            return []
        line_start_secs = [s for s, _ in lines]
        turns = self._run_pipeline(audio_path)
        raw_labels = self._snap_turns_to_lines(turns, line_start_secs)
        speakers = self._renumber_speakers(raw_labels)
        return [
            Utterance(start_sec=start, end_sec=start, speaker=spk, text=text)
            for (start, text), spk in zip(lines, speakers)
        ]

    @staticmethod
    def _validate_wav(audio_path: Path) -> None:
        """Cheap RIFF-header probe so a truncated .raw fails clearly, not cryptically."""
        import wave
        try:
            with wave.open(str(audio_path), "rb") as w:
                if w.getnframes() == 0:
                    raise ValueError(f"{audio_path} is empty (0 frames).")
        except wave.Error as e:
            raise ValueError(f"{audio_path} is not a valid WAV: {e}") from e

    def _load_pipeline(self):
        """Lazy-load the pyannote pipeline. Cached in self._pipeline across calls."""
        if self._pipeline is not None:
            return self._pipeline
        try:
            from pyannote.audio import Pipeline  # type: ignore
        except ImportError as e:
            raise ImportError(
                "pyannote.audio is required for diarization. "
                "Install with: pip install -e '.[diarize]'"
            ) from e
        try:
            import torch  # type: ignore
        except ImportError as e:
            raise ImportError(
                "torch is required for diarization. "
                "Install with: pip install -e '.[diarize]'"
            ) from e

        # pyannote 4.x renamed the auth kwarg from `use_auth_token` to `token`;
        # the [diarize] extra allows >=3.1, so support both.
        def _load(**auth):
            return Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", **auth)

        try:
            try:
                pipeline = _load(token=self.hf_token)
            except TypeError:
                pipeline = _load(use_auth_token=self.hf_token)
        except Exception as e:  # noqa: BLE001 — gated/auth/network → clear, not a traceback
            raise ValueError(
                "Could not load the pyannote pipeline — your HuggingFace token likely "
                "lacks access to a gated model (or auth/network failed). Accept the "
                "license for the gated repo named in the error below, then retry "
                "(use `--relogin` if your token changed). Note: `speaker-diarization-3.1` "
                "pulls several gated dependencies — you must accept EACH one "
                "(segmentation-3.0 and, on pyannote 4.x, speaker-diarization-community-1).\n"
                f"Underlying error: {e}"
            ) from e
        if pipeline is None:
            raise ValueError(
                "pyannote returned no pipeline — your HuggingFace token likely lacks "
                "access to the gated models. Accept the licenses at "
                "https://huggingface.co/pyannote/speaker-diarization-3.1 and "
                "https://huggingface.co/pyannote/segmentation-3.0, then retry."
            )
        if self.use_mps and getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            try:
                pipeline.to(torch.device("mps"))
            except Exception as e:  # noqa: BLE001 — any MPS/op failure → CPU fallback
                import sys
                sys.stderr.write(f"MPS unavailable for pyannote ({e}); falling back to CPU.\n")
                pipeline.to(torch.device("cpu"))
        else:
            pipeline.to(torch.device("cpu"))
        self._pipeline = pipeline
        return self._pipeline

    def _run_pipeline(self, audio_path: Path) -> List[Tuple[float, float, int]]:
        """Run pyannote diarization. Returns (start_sec, end_sec, raw_speaker_idx) per turn."""
        self._validate_wav(audio_path)
        pipeline = self._load_pipeline()
        if self.num_speakers is not None:
            result = pipeline(str(audio_path), num_speakers=self.num_speakers)
        else:
            result = pipeline(str(audio_path))
        # pyannote 4.x returns a DiarizeOutput (Annotation lives on
        # `.speaker_diarization`); 3.x / legacy mode returns the Annotation directly.
        annotation = getattr(result, "speaker_diarization", result)
        out: List[Tuple[float, float, int]] = []
        for turn, _, label in annotation.itertracks(yield_label=True):
            idx = int(label.rsplit("_", 1)[-1])  # "SPEAKER_00" → 0
            out.append((float(turn.start), float(turn.end), idx))
        return out
