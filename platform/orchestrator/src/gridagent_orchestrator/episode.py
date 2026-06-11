"""Durable per-episode log.

One JSONL file per episode, append-only, replayable. The log is the artifact
the trajectory-harvesting loop consumes to seed new exemplars.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .verifier import Decision

EventCallback = Callable[[dict[str, Any]], None]
"""Called synchronously with each record as it is appended to the log."""


@dataclass
class EpisodeStep:
    step: int
    tool: str
    arguments: dict[str, Any]
    value: Any
    signal: dict[str, Any]
    decision: Decision
    attempt: int = 1
    ts: float = field(default_factory=time.time)


@dataclass
class Episode:
    episode_id: str
    goal: str
    log_path: Path
    steps: list[EpisodeStep] = field(default_factory=list)
    # Observer for live consumers (CLI renderer, SSE bridge). Receives the
    # same dict that lands in the JSONL, after it is written.
    on_event: EventCallback | None = None

    @classmethod
    def new(cls, goal: str, root: Path, *, on_event: EventCallback | None = None) -> "Episode":
        episode_id = uuid.uuid4().hex[:12]
        root.mkdir(parents=True, exist_ok=True)
        log_path = root / f"episode_{episode_id}.jsonl"
        ep = cls(episode_id=episode_id, goal=goal, log_path=log_path, on_event=on_event)
        ep._append({"event": "start", "goal": goal, "episode_id": episode_id, "ts": time.time()})
        return ep

    def append_step(self, step: EpisodeStep) -> None:
        self.steps.append(step)
        rec = asdict(step)
        rec["decision"] = step.decision.value
        rec["event"] = "step"
        self._append(rec)

    def finish(self, summary: str) -> None:
        self._append({"event": "finish", "summary": summary, "ts": time.time()})

    def _append(self, record: dict[str, Any]) -> None:
        with self.log_path.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")
        if self.on_event is not None:
            self.on_event(record)
