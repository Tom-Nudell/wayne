"""Visual QA gate for the data pipeline.

The gate is the wall between platform/data's build and tile promotion
to the public R2 prefix. Six checks (brief §7), each returning a
CheckResult; the orchestrator aggregates them into a GateReport.

Today most checks are skeletons that return ``skipped`` — they land
for real in Phase 1 of the engineering brief. The license-sidecar
check is the one with real behavior today: walks the bundle dir and
fails if any PMTiles archive is missing its sidecar.
"""

from gridagent_data.qa.gate import run_gate
from gridagent_data.qa.models import CheckResult, CheckStatus, GateReport

__all__ = ["run_gate", "CheckResult", "CheckStatus", "GateReport"]
