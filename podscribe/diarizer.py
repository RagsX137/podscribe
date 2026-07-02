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

    # parsing / snapping / diarize() added in Task 7; _run_pipeline in Task 8.
