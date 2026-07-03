"""Live terminal rendering of an episode event stream.

Pure consumers of the event dicts ``Episode._append`` emits — no orchestrator
logic lives here. Two renderers share the interface:

* ``RichRenderer`` — a ``rich.live.Live`` panel: one row per tool call with
  the verifier's decision color-coded, a spinner while the planner thinks,
  and a summary panel at the end.
* ``JsonlRenderer`` — re-emits each event as one JSON line on stdout, for
  machine consumers (the web SSE bridge spawns the CLI in this mode).

Both attach via ``Episode.new(..., on_event=renderer)`` — the renderer *is*
the callback.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

# Verifier decisions → terminal colors. Alarm colors are earned: green
# advances quietly, yellow means the model is re-planning, red ends the run.
_DECISION_STYLE = {
    "advance": "bold green",
    "retry": "bold yellow",
    "replan": "bold yellow",
    "abort": "bold red",
}


def _summarise_args(arguments: dict[str, Any], limit: int = 60) -> str:
    parts = []
    for k, v in arguments.items():
        if v is None:
            continue
        s = json.dumps(v, default=str) if isinstance(v, (dict, list)) else str(v)
        parts.append(f"{k}={s}")
    joined = ", ".join(parts)
    return joined if len(joined) <= limit else joined[: limit - 1] + "…"


def _summarise_signal(signal: dict[str, Any], limit: int = 70) -> str:
    parts = []
    for k, v in signal.items():
        if isinstance(v, float):
            v = f"{v:.4g}"
        parts.append(f"{k}={v}")
    joined = " ".join(str(p) for p in parts)
    return joined if len(joined) <= limit else joined[: limit - 1] + "…"


class RichRenderer:
    """Callable event observer that drives a live terminal panel."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self._steps: list[dict[str, Any]] = []
        self._notes: list[str] = []
        self._goal: str = ""
        self._episode_id: str = ""
        self._summary: str | None = None
        self._workflow: bool = False
        self._live: Live | None = None

    # -- context manager ----------------------------------------------------

    def __enter__(self) -> "RichRenderer":
        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=8,
            transient=False,
        )
        self._live.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._live is not None:
            self._live.update(self._render(), refresh=True)
            self._live.__exit__(*exc)
            self._live = None

    # -- event sink ----------------------------------------------------------

    def __call__(self, record: dict[str, Any]) -> None:
        event = record.get("event")
        if event == "start":
            self._goal = str(record.get("goal", ""))
            self._episode_id = str(record.get("episode_id", ""))
        elif event == "workflow":
            nodes = record.get("nodes") or []
            self._notes.append(
                f"workflow {record.get('workflow')}: "
                + " → ".join(str(n.get("tool", "?")) for n in nodes)
            )
            self._workflow = True
        elif event == "step":
            self._steps.append(record)
        elif event == "escalate":
            self._notes.append(
                f"escalating to agent at node {record.get('node')}: {record.get('reason')}"
            )
            self._workflow = False
        elif event == "finish":
            self._summary = str(record.get("summary", ""))
        if self._live is not None:
            self._live.update(self._render(), refresh=True)

    # -- drawing ------------------------------------------------------------

    def _render(self) -> Panel:
        table = Table(box=None, pad_edge=False, show_header=bool(self._steps))
        table.add_column("#", justify="right", style="dim", width=3)
        table.add_column("tool", style="bold")
        table.add_column("arguments", style="dim", overflow="fold")
        table.add_column("signal", overflow="fold")
        table.add_column("verdict")

        for rec in self._steps:
            decision = str(rec.get("decision", ""))
            attempt = int(rec.get("attempt", 1))
            verdict = Text(
                decision.upper() + (f" (try {attempt})" if attempt > 1 else ""),
                style=_DECISION_STYLE.get(decision, "white"),
            )
            table.add_row(
                str(rec.get("step", "")),
                str(rec.get("tool", "")),
                _summarise_args(rec.get("arguments") or {}),
                _summarise_signal(rec.get("signal") or {}),
                verdict,
            )

        body: list[Any] = [Text(n, style="dim italic") for n in self._notes]
        if self._steps:
            body.append(table)
        if self._summary is None:
            spinner_text = " running workflow…" if self._workflow else " planner thinking…"
            body.append(Spinner("dots", text=Text(spinner_text, style="dim")))
        else:
            body.append(
                Panel(self._summary, title="summary", border_style="green", expand=False)
            )

        title = Text.assemble(
            ("episode ", "dim"),
            (self._episode_id or "…", "bold"),
            ("  ", ""),
            (self._goal[:80], "italic dim"),
        )
        return Panel(Group(*body), title=title, border_style="bright_black")


class JsonlRenderer:
    """Event observer that re-emits each record as one JSON line on stdout.

    Machine consumers (e.g. the web /api/study SSE bridge) read these lines;
    keep stdout clean of anything else when this renderer is active.
    """

    def __call__(self, record: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(record, default=str) + "\n")
        sys.stdout.flush()
