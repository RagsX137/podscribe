from __future__ import annotations

import json
from pathlib import Path

from benchmarks.eval_rate import (
    append_rating,
    load_ratings,
    randomize_pair,
    session_state,
)


def test_randomize_pair_returns_two_positions():
    pair = {"challenger": {"model": "a", "text": "x"}, "champion": {"model": "b", "text": "y"}}
    randomized = randomize_pair(pair, seed=42)
    assert "left" in randomized and "right" in randomized
    assert randomized["left"]["text"] in ("x", "y")
    assert randomized["right"]["text"] in ("x", "y")
    assert randomized["left"]["text"] != randomized["right"]["text"]


def test_session_state_conceals_identities_until_reveal():
    state = session_state(pairs=[("id1", {"challenger": {"model": "a", "text": "x"}, "champion": {"model": "b", "text": "y"}})])
    blob = json.dumps(state.as_dict())
    assert "model" not in blob
    state.reveal()
    blob2 = json.dumps(state.as_dict())
    assert state.identities_visible is True


def test_append_rating_writes_json(tmp_path):
    p = tmp_path / "ratings.json"
    append_rating(p, {"pair_id": "p1", "choice": "left", "run": 0})
    ratings = load_ratings(p)
    assert len(ratings) == 1
    assert ratings[0]["choice"] == "left"


def test_append_rating_appends_to_existing(tmp_path):
    p = tmp_path / "ratings.json"
    append_rating(p, {"pair_id": "p1", "choice": "left", "run": 0})
    append_rating(p, {"pair_id": "p2", "choice": "tie", "run": 0})
    ratings = load_ratings(p)
    assert len(ratings) == 2
