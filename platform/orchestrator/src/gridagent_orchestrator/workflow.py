"""Declarative workflows: fixed tool sequences executed without a planner.

A workflow is the learned, frozen form of a study the agent has already
figured out — the N-1 playbook from ``planner._INSTRUCTIONS`` transcribed
into data (see ``workflows/n1_contingency.yaml``). Running one costs zero
model requests: nodes execute in order, the same rule-based verifier gates
every result, and the same ``EpisodeStep`` records flow to every existing
consumer (CLI renderers, the web NDJSON bridge, overlay export).

A workflow never improvises. When a node fails verification (REPLAN) or a
tool raises, the runner returns an ``escalate`` outcome and the caller hands
the episode to the agent with the completed prefix as context (``run.py``).
ABORT means a numerical bug — nobody retries that, agent included.

Specs are loaded from the package ``workflows/`` directory plus an optional
``GRIDAGENT_WORKFLOW_ROOT`` directory (user-composed workflows, Track 2).
"""

from __future__ import annotations

import copy
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from gridagent_tools import TOOL_REGISTRY

from .episode import Episode, EpisodeStep
from .verifier import Decision, Verifier


class WorkflowError(ValueError):
    """Spec problem: unknown tool/port, bad reference, missing input."""


# ---------------------------------------------------------------------------
# Activity ports
# ---------------------------------------------------------------------------
# Named outputs an activity (a registered tool) exposes to downstream
# bindings. Paths are dotted lookups rooted at {"value": .., "signal": ..};
# integer segments index into lists. Workflows reference ``$node.port``
# instead of reaching into raw result shapes, so specs stay readable and
# composition has a typed surface to validate against.
ACTIVITY_PORTS: dict[str, dict[str, str]] = {
    "list_data_snapshots": {
        "latest": "value.snapshots.0.id",
        "count": "signal.count",
    },
    "query_grid": {
        "snapshot_id": "value.snapshot_id",
        "row_count": "signal.row_count",
    },
    "create_scenario": {
        "scenario_id": "signal.scenario_id",
        "snapshot_id": "value.snapshot_id",
    },
    "inspect_scenario": {
        "scenario_id": "signal.scenario_id",
    },
    "run_power_flow": {
        "converged": "signal.converged",
        "max_mismatch_mw": "signal.max_mismatch_mw",
    },
    "run_n1_contingency": {
        "n_overloads": "signal.n_overloads",
        "n_screened": "signal.n_screened",
        "n_islanding": "signal.n_islanding",
        "worst_loading_pct": "signal.worst_loading_pct",
        "worst": "value.ranking.0",
        "ranking": "value.ranking",
    },
    "run_production_cost": {
        "objective": "signal.objective",
        "solver_status": "signal.solver_status",
        "slack_mw": "signal.slack_mw",
    },
}


@dataclass(frozen=True)
class WorkflowNode:
    id: str
    tool: str
    bind: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowSpec:
    name: str
    description: str
    inputs: dict[str, dict[str, Any]]
    nodes: tuple[WorkflowNode, ...]
    # Templates with {inputs.x} / {node.port} references. ``goal`` renders
    # before execution (inputs only); ``summary`` renders after, from node
    # outputs. Unresolvable references render as "n/a", not errors — the
    # study result must survive a template typo.
    goal: str | None = None
    summary: str | None = None

    def tool_of(self, node_id: str) -> str:
        for node in self.nodes:
            if node.id == node_id:
                return node.tool
        raise WorkflowError(f"workflow {self.name!r}: no node {node_id!r}")


OutcomeStatus = Literal["completed", "escalate", "aborted"]


@dataclass
class WorkflowOutcome:
    status: OutcomeStatus
    failed_node: str | None = None
    reason: str | None = None
    # node_id -> {"value": .., "signal": ..} for every node that ADVANCEd.
    context: dict[str, dict[str, Any]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_BUILTIN_DIR = Path(__file__).parent / "workflows"


def workflow_dirs() -> list[Path]:
    dirs = [_BUILTIN_DIR]
    extra = os.environ.get("GRIDAGENT_WORKFLOW_ROOT")
    if extra:
        dirs.append(Path(extra))
    return [d for d in dirs if d.is_dir()]


def list_workflows() -> list[str]:
    names: list[str] = []
    for d in workflow_dirs():
        for p in sorted(d.glob("*.yaml")):
            if p.stem not in names:
                names.append(p.stem)
    return names


# Workflow names are filenames. Without this gate, a name like
# "../../tmp/evil" loads YAML from anywhere on disk — latent today (the web
# bridge hardcodes the name) but a real hole the moment Track 2 plumbs
# user-supplied names through the request.
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def load_workflow(name: str) -> WorkflowSpec:
    if not _NAME_RE.match(name):
        raise WorkflowError(f"Invalid workflow name {name!r} (allowed: letters, digits, _, -)")
    for d in workflow_dirs():
        path = d / f"{name}.yaml"
        if path.exists():
            return parse_workflow(path.read_text(), source=str(path))
    raise WorkflowError(f"No workflow named {name!r}. Available: {list_workflows()}")


def parse_workflow(text: str, *, source: str = "<inline>") -> WorkflowSpec:
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict) or "workflow" not in raw:
        raise WorkflowError(f"{source}: expected a mapping with a 'workflow' name")
    nodes = tuple(
        WorkflowNode(id=str(n["id"]), tool=str(n["tool"]), bind=dict(n.get("bind") or {}))
        for n in raw.get("nodes") or []
    )
    spec = WorkflowSpec(
        name=str(raw["workflow"]),
        description=str(raw.get("description", "")).strip(),
        inputs={str(k): dict(v or {}) for k, v in (raw.get("inputs") or {}).items()},
        nodes=nodes,
        goal=raw.get("goal"),
        summary=raw.get("summary"),
    )
    _validate(spec, source)
    return spec


def _iter_refs(value: Any):
    """Yield every ``$ref`` string inside a binding value, recursively."""
    if isinstance(value, str) and value.startswith("$"):
        yield value[1:]
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_refs(v)
    elif isinstance(value, list):
        for v in value:
            yield from _iter_refs(v)


def _validate(spec: WorkflowSpec, source: str) -> None:
    if not spec.nodes:
        raise WorkflowError(f"{source}: workflow {spec.name!r} has no nodes")
    seen: dict[str, str] = {}  # node id -> tool
    for node in spec.nodes:
        where = f"{source}: node {node.id!r}"
        if node.id in seen or node.id == "inputs":
            raise WorkflowError(f"{where}: duplicate or reserved node id")
        if node.tool not in TOOL_REGISTRY:
            raise WorkflowError(f"{where}: unknown tool {node.tool!r}")
        for ref in _iter_refs(node.bind):
            head, _, rest = ref.partition(".")
            if head == "inputs":
                if rest.split(".")[0] not in spec.inputs:
                    raise WorkflowError(f"{where}: ${ref} is not a declared input")
            elif head in seen:
                port = rest.split(".")[0]
                if port not in ACTIVITY_PORTS.get(seen[head], {}):
                    raise WorkflowError(
                        f"{where}: ${ref} — tool {seen[head]!r} has no port {port!r}"
                    )
            else:
                raise WorkflowError(f"{where}: ${ref} references a later or unknown node")
        seen[node.id] = node.tool


# ---------------------------------------------------------------------------
# Reference resolution
# ---------------------------------------------------------------------------


def _lookup(obj: Any, path: str) -> Any:
    cur = obj
    for seg in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(seg)]
        elif isinstance(cur, dict):
            cur = cur[seg]
        else:
            raise KeyError(f"cannot descend into {type(cur).__name__} at {seg!r}")
    return cur


def _resolve_ref(ref: str, spec: WorkflowSpec, inputs: dict, results: dict) -> Any:
    head, _, rest = ref.partition(".")
    if head == "inputs":
        return _lookup(inputs, rest)
    if head not in results:
        raise KeyError(f"node {head!r} has no result yet")
    port, _, sub = rest.partition(".")
    path = ACTIVITY_PORTS[spec.tool_of(head)][port]
    val = _lookup(results[head], path)
    return _lookup(val, sub) if sub else val


def _resolve_value(value: Any, spec: WorkflowSpec, inputs: dict, results: dict) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return _resolve_ref(value[1:], spec, inputs, results)
    if isinstance(value, dict):
        return {k: _resolve_value(v, spec, inputs, results) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(v, spec, inputs, results) for v in value]
    return value


def resolve_inputs(spec: WorkflowSpec, provided: dict[str, Any] | None) -> dict[str, Any]:
    provided = provided or {}
    unknown = set(provided) - set(spec.inputs)
    if unknown:
        raise WorkflowError(
            f"workflow {spec.name!r}: unknown inputs {sorted(unknown)}; "
            f"declared: {sorted(spec.inputs)}"
        )
    out: dict[str, Any] = {}
    for name, decl in spec.inputs.items():
        if name in provided:
            out[name] = provided[name]
        elif "default" in decl:
            # Deep-copy so a run can't mutate the spec's default in place
            # and leak state into the next run.
            out[name] = copy.deepcopy(decl["default"])
        elif decl.get("required"):
            raise WorkflowError(f"workflow {spec.name!r}: missing required input {name!r}")
        else:
            out[name] = None
    return out


def resolved_ports(
    spec: WorkflowSpec, node_id: str, result: dict[str, Any]
) -> dict[str, Any]:
    """Port name -> value for a completed node's result.

    The escalation prompt uses this instead of raw signals: signals don't
    always carry what a downstream consumer needs (e.g. list_data_snapshots'
    signal has counts but not the snapshot id the agent must reuse).
    """
    out: dict[str, Any] = {}
    for port, path in ACTIVITY_PORTS.get(spec.tool_of(node_id), {}).items():
        try:
            out[port] = _lookup(result, path)
        except (KeyError, IndexError, ValueError):
            continue
    return out


_TEMPLATE_RE = re.compile(r"\{([A-Za-z0-9_.]+)\}")


def render_template(
    template: str, spec: WorkflowSpec, inputs: dict, results: dict
) -> str:
    def _sub(m: re.Match[str]) -> str:
        try:
            val = _resolve_ref(m.group(1), spec, inputs, results)
        except (KeyError, IndexError, ValueError):
            return "n/a"
        if isinstance(val, float):
            return f"{val:.4g}"
        return str(val)

    return _TEMPLATE_RE.sub(_sub, template).strip()


def render_goal(spec: WorkflowSpec, inputs: dict[str, Any]) -> str:
    if spec.goal:
        return render_template(spec.goal, spec, inputs, {})
    return f"Workflow {spec.name}: {spec.description}"


def render_summary(spec: WorkflowSpec, inputs: dict, results: dict) -> str:
    if spec.summary:
        return render_template(spec.summary, spec, inputs, results)
    return f"Workflow {spec.name} completed: all {len(spec.nodes)} steps verified."


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

# RETRY re-runs a node with identical arguments, so it only covers transient
# failures; verifier rules escalate themselves (e.g. _power_flow_rule flips
# to REPLAN on attempt 2). This cap is the backstop against a rule that
# returns RETRY forever.
_MAX_NODE_ATTEMPTS = 3


def run_workflow(
    spec: WorkflowSpec,
    inputs: dict[str, Any],
    *,
    verifier: Verifier,
    episode: Episode,
) -> WorkflowOutcome:
    """Execute every node in order, gated by the verifier. Zero model calls.

    Emits one ``workflow`` record up front (so live consumers can draw the
    full plan before anything runs) and one ``EpisodeStep`` per attempt,
    stamped with the node id.
    """
    episode.append_record(
        {
            "event": "workflow",
            "workflow": spec.name,
            "nodes": [{"id": n.id, "tool": n.tool} for n in spec.nodes],
            "ts": time.time(),
        }
    )
    results: dict[str, dict[str, Any]] = {}
    step_no = len(episode.steps)

    for node in spec.nodes:
        try:
            kwargs = {
                k: _resolve_value(v, spec, inputs, results) for k, v in node.bind.items()
            }
        except (KeyError, IndexError, ValueError) as exc:
            return WorkflowOutcome(
                "escalate", node.id, f"binding failed: {exc}", results
            )

        for attempt in range(1, _MAX_NODE_ATTEMPTS + 1):
            step_no += 1
            try:
                result = TOOL_REGISTRY[node.tool].fn(**kwargs)
            except Exception as exc:  # noqa: BLE001 — any tool failure escalates
                episode.append_step(
                    EpisodeStep(
                        step=step_no,
                        tool=node.tool,
                        arguments=kwargs,
                        value=None,
                        signal={"error": str(exc)},
                        decision=Decision.REPLAN,
                        attempt=attempt,
                        node=node.id,
                    )
                )
                return WorkflowOutcome(
                    "escalate", node.id, f"{node.tool} raised: {exc}", results
                )

            decision = verifier.decide(node.tool, result.signal, attempt=attempt)
            episode.append_step(
                EpisodeStep(
                    step=step_no,
                    tool=node.tool,
                    arguments=kwargs,
                    value=result.value,
                    signal=result.signal,
                    decision=decision,
                    attempt=attempt,
                    node=node.id,
                )
            )
            if decision is Decision.ADVANCE:
                results[node.id] = {"value": result.value, "signal": result.signal}
                break
            if decision is Decision.RETRY:
                continue
            if decision is Decision.ABORT:
                return WorkflowOutcome(
                    "aborted", node.id, f"verifier abort: {result.signal}", results
                )
            return WorkflowOutcome(
                "escalate", node.id, f"verifier replan: {result.signal}", results
            )
        else:
            return WorkflowOutcome(
                "escalate",
                node.id,
                f"retries exhausted after {_MAX_NODE_ATTEMPTS} attempts",
                results,
            )

    return WorkflowOutcome("completed", context=results)
