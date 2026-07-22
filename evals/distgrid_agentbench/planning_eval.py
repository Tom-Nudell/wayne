"""DistGrid-AgentBench planning eval: query → workflow, scored against ground truth.

Measures the capability Wayne's planner depends on — mapping a natural-language
grid question to the right tool workflow — using the benchmark's 200 tasks and
its 108-tool catalog. No benchmark tool is executed and no proprietary feeder
data is touched: the model plans, and we score the *plan* against the canonical
workflow graph (see scorer.py for metric definitions).

Usage:
    python3 planning_eval.py --benchmark-dir /path/to/DistGrid-AgentBench \
        [--families general,powerflow] [--limit 20] [--model gemma4:26b] \
        [--base-url http://localhost:11434/v1] [--out results]

The model endpoint is OpenAI-compatible (same convention as the Wayne planner:
GRIDAGENT_LLM_BASE_URL / GRIDAGENT_LLM_MODEL env vars are honored as defaults).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from scorer import analyze, hallucinated_tools

_SYSTEM = """\
You plan tool workflows for a power distribution grid analysis platform.

Available tools (name: description):
{catalog}

Given the user's question, respond with ONLY a JSON array of the tool calls
that answer it, in execution order:
[{{"name": "<tool name>", "arguments": {{...}}}}, ...]

Rules:
- Use only tool names from the list above.
- Use the minimum number of calls that fully answers the question.
- Load/setup tools come before analysis tools that depend on them.
- No prose, no markdown fences — the JSON array only.
"""


def load_benchmark(root: Path, families: set[str] | None) -> tuple[list[dict], set[str], str]:
    tasks = [
        json.loads(line)
        for line in (root / "benchmark" / "tasks.jsonl").read_text().splitlines()
        if line.strip()
    ]
    gt: dict[tuple[str, str], list[dict]] = {}
    for family_dir in (root / "benchmark" / "tasks").iterdir():
        wf_path = family_dir / "workflows.json"
        if not wf_path.exists():
            continue
        for item in json.loads(wf_path.read_text()):
            gt[(family_dir.name, str(item["id"]))] = item["workflow"]
    manifest = json.loads((root / "data" / "tool_manifest.json").read_text())
    known = {str(t["name"]) for t in manifest}
    catalog = "\n".join(f"- {t['name']}: {t['description']}" for t in manifest)

    cases = []
    for task in tasks:
        if families and task["family"] not in families:
            continue
        ref = gt.get((task["family"], str(task["family_id"])))
        if ref is None:
            continue  # ground truth missing for this task — skip, count later
        cases.append({**task, "gt_workflow": ref})
    return cases, known, catalog


def plan(query: str, catalog: str, model: str, base_url: str, timeout: int = 180) -> list[dict]:
    body = json.dumps(
        {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _SYSTEM.format(catalog=catalog)},
                {"role": "user", "content": query},
            ],
        }
    ).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer ollama"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content = json.load(resp)["choices"][0]["message"]["content"]
    return _extract_workflow(content)


def _extract_workflow(text: str) -> list[dict]:
    """Pull the first JSON array out of the response, fences and all."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        text = text[4:] if text.startswith("json") else text
    start = text.find("[")
    if start == -1:
        raise ValueError(f"no JSON array in response: {text[:120]!r}")
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                parsed = json.loads(text[start : i + 1])
                break
    else:
        raise ValueError("unbalanced JSON array in response")
    if not isinstance(parsed, list):
        raise ValueError("response is not a list")
    return [
        {"name": str(s.get("name")), "arguments": dict(s.get("arguments") or {})}
        for s in parsed
        if isinstance(s, dict)
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--benchmark-dir", type=Path, required=True)
    ap.add_argument("--families", default=None, help="csv of task families; default all")
    ap.add_argument("--limit", type=int, default=None, help="max tasks overall")
    ap.add_argument("--model", default=os.environ.get("GRIDAGENT_LLM_MODEL", "gemma4:e12b"))
    ap.add_argument(
        "--base-url",
        default=os.environ.get("GRIDAGENT_LLM_BASE_URL", "http://localhost:11434/v1"),
    )
    ap.add_argument("--out", type=Path, default=Path("results"))
    args = ap.parse_args()

    families = set(args.families.split(",")) if args.families else None
    cases, known, catalog = load_benchmark(args.benchmark_dir, families)
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("no tasks matched", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    results_path = args.out / f"planning_{args.model.replace(':', '_')}_{stamp}.jsonl"

    rows = []
    for n, case in enumerate(cases, 1):
        t0 = time.time()
        try:
            agent_wf = plan(case["query"], catalog, args.model, args.base_url)
            success, reason, precision = analyze(agent_wf, case["gt_workflow"])
            invented = hallucinated_tools(agent_wf, known)
        except Exception as exc:  # noqa: BLE001 -- a bad response is a scored failure
            agent_wf, success, reason, precision, invented = [], False, f"error: {exc}", 0.0, []
        row = {
            "id": case["id"],
            "family": case["family"],
            "query": case["query"],
            "success": success,
            "precision": precision,
            "reason": reason,
            "hallucinated_tools": invented,
            "agent_workflow": agent_wf,
            "gt_workflow": case["gt_workflow"],
            "seconds": round(time.time() - t0, 1),
        }
        rows.append(row)
        with results_path.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
        mark = "PASS" if success else "fail"
        print(f"[{n}/{len(cases)}] {case['family']}/{case['id']} {mark} ({row['seconds']}s)", flush=True)

    by_family: dict[str, list[dict]] = {}
    for row in rows:
        by_family.setdefault(row["family"], []).append(row)
    print(f"\nmodel={args.model}  tasks={len(rows)}")
    print(f"{'family':<14}{'n':>4}{'P@1':>8}{'precision':>11}{'halluc.':>9}")
    for family, fam_rows in sorted(by_family.items()):
        p1 = 100 * sum(r["success"] for r in fam_rows) / len(fam_rows)
        prec = 100 * sum(r["precision"] for r in fam_rows) / len(fam_rows)
        hall = sum(bool(r["hallucinated_tools"]) for r in fam_rows)
        print(f"{family:<14}{len(fam_rows):>4}{p1:>7.1f}%{prec:>10.1f}%{hall:>9}")
    p1 = 100 * sum(r["success"] for r in rows) / len(rows)
    prec = 100 * sum(r["precision"] for r in rows) / len(rows)
    print(f"{'OVERALL':<14}{len(rows):>4}{p1:>7.1f}%{prec:>10.1f}%")
    print(f"\nresults: {results_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
