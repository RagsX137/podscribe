"""HuggingFace token resolution for pyannote.audio (first-run interactive login).

Token storage lives outside the repo tree at ~/.config/podscribe/hf_token (mode 0o600)
to survive import/export and match standard CLI conventions (gh, huggingface-cli).
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path
from typing import Optional

HF_TOKEN_ENV = "HF_TOKEN"
HF_TOKEN_PATH = Path.home() / ".config" / "podscribe" / "hf_token"
HF_TOKEN_URL = "https://huggingface.co/settings/tokens"

HF_LOGIN_INSTRUCTIONS = (
    "pyannote.audio requires a HuggingFace token.\n"
    "  1. Accept the model license at:\n"
    "     https://huggingface.co/pyannote/speaker-diarization-community-1\n"
    "     (and any gated sub-models it prompts for on first run)\n"
    "  2. Create a read token at:\n"
    "     " + HF_TOKEN_URL + "\n"
    "  3. Paste the token below (input is masked):\n"
)

DIARIZE_NO_TOKEN_MSG = (
    "No HuggingFace token found. Set $HF_TOKEN, or run `podscribe diarize` in a TTY "
    "to be prompted. Create a token at " + HF_TOKEN_URL + " and accept the two "
    "pyannote model licenses first (see README)."
)


def get_hf_token(*, interactive: bool = True) -> Optional[str]:
    """Resolve HF token. Order: $HF_TOKEN → cached file → interactive prompt.

    Returns None when not found and (not interactive OR not a TTY).
    """
    env_token = os.environ.get(HF_TOKEN_ENV)
    if env_token:
        return env_token.strip() or None
    if HF_TOKEN_PATH.exists():
        cached = HF_TOKEN_PATH.read_text().strip()
        if cached:
            return cached
    if interactive and sys.stdin.isatty():
        return prompt_for_hf_token()
    return None


def save_hf_token(token: str) -> None:
    """Persist token to ~/.config/podscribe/hf_token with mode 0o600."""
    HF_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    HF_TOKEN_PATH.write_text(token)
    os.chmod(HF_TOKEN_PATH, 0o600)


def prompt_for_hf_token() -> Optional[str]:
    """Print instructions then read a token via getpass. Returns None on decline/non-TTY."""
    if not sys.stdin.isatty():
        print(DIARIZE_NO_TOKEN_MSG, file=sys.stderr)
        return None
    print(HF_LOGIN_INSTRUCTIONS)
    try:
        token = getpass.getpass(prompt="HF token: ")
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    token = token.strip()
    if not token:
        return None
    save_hf_token(token)
    return token
