"""Embedding-based retrieval over hand-seeded reasoning trajectories.

Stub: for now returns trajectories in deterministic name order so the rest of
the pipeline can be exercised without an embedding model. Real implementation
will load ``sentence-transformers/all-MiniLM-L6-v2`` lazily.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Trajectory:
    name: str
    text: str


def _store_root() -> Path:
    return Path(__file__).resolve().parent / "trajectory_store"


def load_all() -> list[Trajectory]:
    root = _store_root()
    if not root.exists():
        return []
    out: list[Trajectory] = []
    for path in sorted(root.glob("*.md")):
        if path.name.startswith("_"):
            continue
        out.append(Trajectory(name=path.stem, text=path.read_text()))
    return out


def retrieve(goal: str, k: int = 3) -> list[Trajectory]:
    """Return up to ``k`` trajectories ranked by relevance to ``goal``.

    Stub ranking: keyword overlap on lowercase tokens. Replace with embedding
    similarity once a model is wired in.
    """
    candidates = load_all()
    if not candidates:
        return []
    goal_tokens = {t for t in goal.lower().split() if len(t) > 3}

    def score(t: Trajectory) -> int:
        body = t.text.lower()
        return sum(body.count(tok) for tok in goal_tokens)

    return sorted(candidates, key=score, reverse=True)[:k]
