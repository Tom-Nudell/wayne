"""PowerChain-style verifiable orchestrator over the gridagent tool surface.

Built on pydantic-ai: the framework handles tool-call routing and history;
our verifier hooks into every tool result via ModelRetry, giving the
PowerChain "tool-grounded supervisory signal" property without a bespoke
agent loop.
"""

from .episode import Episode, EpisodeStep
from .planner import OrchestratorDeps, make_agent
from .run import run_episode, run_workflow_episode
from .verifier import Decision, Verifier
from .workflow import WorkflowSpec, list_workflows, load_workflow, run_workflow

__all__ = [
    "Decision",
    "Episode",
    "EpisodeStep",
    "OrchestratorDeps",
    "Verifier",
    "WorkflowSpec",
    "list_workflows",
    "load_workflow",
    "make_agent",
    "run_episode",
    "run_workflow",
    "run_workflow_episode",
]
