"""Result types for the visual QA gate."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

CheckStatus = Literal["pass", "warn", "fail", "skipped"]


class CheckResult(BaseModel):
    """One check's outcome.

    ``artifact_paths`` is for byproducts the human reviewer wants —
    diff reports, regression screenshots, density-stats CSVs. They are
    written by the check and referenced here so CI can upload them.
    """

    name: str
    status: CheckStatus
    summary: str
    details: list[str] = []
    artifact_paths: list[str] = []


class GateReport(BaseModel):
    """Aggregate verdict + per-check breakdown.

    ``overall`` is the worst status across results, with the priority
    order ``pass`` < ``skipped`` < ``warn`` < ``fail``. The CLI exits
    non-zero only on ``fail`` — ``warn`` is a notice, not a block.
    """

    overall: CheckStatus
    results: list[CheckResult]
