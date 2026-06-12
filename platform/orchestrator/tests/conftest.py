import pytest


@pytest.fixture(autouse=True)
def _isolate_workflow_root(monkeypatch):
    """Workflow discovery reads GRIDAGENT_WORKFLOW_ROOT; tests must not see
    whatever the developer's shell happens to have set."""
    monkeypatch.delenv("GRIDAGENT_WORKFLOW_ROOT", raising=False)
