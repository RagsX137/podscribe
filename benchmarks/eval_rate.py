# benchmarks/eval_rate.py
"""Layer-3 blind human A/B rating: shuffle, conceal, persist.

Module is importable without `rich` so tests can run headless. TUI rendering
lazy-imports tui.py constants at render time only.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def randomize_pair(pair: dict, *, seed: Optional[int] = None) -> dict:
    rng = random.Random(seed)
    a = pair["challenger"]
    b = pair["champion"]
    left, right = (a, b) if rng.random() < 0.5 else (b, a)
    return {"left": left, "right": right}


@dataclass
class SessionState:
    pairs: list
    ratings: list = field(default_factory=list)
    revealed: bool = False

    def as_dict(self) -> dict:
        if self.revealed:
            return {"pairs": self.pairs, "ratings": self.ratings, "revealed": True, "identities_visible": True}

        def _conceal(p):
            pair_dict = p[1] if isinstance(p, tuple) else p
            return {k: {kk: vv for kk, vv in v.items() if kk != "model"} for k, v in pair_dict.items()}

        concealed = [_conceal(p) for p in self.pairs]
        return {"pairs": concealed, "ratings": self.ratings, "revealed": False, "identities_visible": False}

    @property
    def identities_visible(self) -> bool:
        return self.revealed

    def reveal(self) -> None:
        self.revealed = True


def session_state(*, pairs: list) -> SessionState:
    return SessionState(pairs=pairs)


def append_rating(path: Path, rating: dict) -> None:
    existing = load_ratings(path) if path.exists() else []
    existing.append(rating)
    path.write_text(json.dumps(existing, indent=2))


def load_ratings(path: Path) -> list:
    if not path.exists():
        return []
    return json.loads(path.read_text())
