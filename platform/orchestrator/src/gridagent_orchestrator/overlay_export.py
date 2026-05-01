"""Build a GeoJSON overlay from an episode log's last ``run_n1_contingency`` step.

Maps overloaded *monitored* branches as LineStrings (lat/lon from the snapshot
buses table) so the atlas can highlight agent-discovered thermal issues in
``PALETTE.overload`` red.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from gridagent_tools.scenario_tools import load_scenario
from gridagent_tools.snapshot import Snapshot


def _bundle_root() -> Path:
    return Path(os.environ.get("GRIDAGENT_DATA_ROOT", "data_root")) / "bundle"


def _iter_steps(log_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("event") == "step":
            rows.append(rec)
    return rows


def build_n1_overlay_features(
    *,
    ranking: list[dict[str, Any]],
    snapshot: Snapshot,
    max_features: int = 40,
) -> list[dict[str, Any]]:
    buses = snapshot.buses().set_index("bus_id")
    branches = snapshot.branches()
    branch_key = branches["branch_id"].astype(str)

    def linestring_for_branch(branch_id: str) -> dict[str, Any] | None:
        row = branches.loc[branch_key == str(branch_id)]
        if row.empty:
            return None
        r = row.iloc[0]
        try:
            fb = buses.loc[str(r.from_bus_id)]
            tb = buses.loc[str(r.to_bus_id)]
        except KeyError:
            return None
        lat0, lon0 = float(fb["lat"]), float(fb["lon"])
        lat1, lon1 = float(tb["lat"]), float(tb["lon"])
        if not all(map(lambda x: x == x, [lat0, lon0, lat1, lon1])):  # NaN check
            return None
        return {
            "type": "LineString",
            "coordinates": [[lon0, lat0], [lon1, lat1]],
        }

    features: list[dict[str, Any]] = []
    for row in ranking[:max_features]:
        bid = str(row.get("monitored", ""))
        geom = linestring_for_branch(bid)
        if geom is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "kind": "overload",
                    "monitored": bid,
                    "outage": str(row.get("outage", "")),
                    "loading_pct": float(row.get("loading_pct", 0.0)),
                    "post_flow_mw": float(row.get("post_flow_mw", 0.0)),
                    "rating_mva": float(row.get("rating_mva", 0.0)),
                },
            }
        )
    return features


def write_n1_overlay_from_episode(
    episode_log: Path,
    out_path: Path,
    *,
    bundle_root: Path | None = None,
    max_features: int = 40,
) -> int:
    """Parse ``episode_log`` and write a FeatureCollection to ``out_path``.

    Returns the number of features written (0 if none).
    """
    bundle_root = bundle_root or _bundle_root()
    steps = _iter_steps(episode_log)
    n1: dict[str, Any] | None = None
    for rec in reversed(steps):
        if rec.get("tool") == "run_n1_contingency":
            n1 = rec
            break
    if n1 is None:
        raise ValueError(f"No run_n1_contingency step in {episode_log}")

    args = n1.get("arguments") or {}
    scenario_id = args.get("scenario_id")
    if not scenario_id:
        raise ValueError("N-1 step missing scenario_id in arguments")

    scenario = load_scenario(str(scenario_id))
    snapshot_id = scenario.get("snapshot_id")
    if not snapshot_id:
        candidates = sorted(
            (p for p in bundle_root.iterdir() if p.is_dir() and p.name.startswith("snapshot_")),
            reverse=True,
        )
        if not candidates:
            raise FileNotFoundError(f"No snapshot_id on scenario and no snapshots under {bundle_root}")
        snapshot_id = candidates[0].name

    snapshot = Snapshot.at(bundle_root / snapshot_id)
    value = n1.get("value") or {}
    ranking = value.get("ranking") or []
    if not ranking:
        collection = {"type": "FeatureCollection", "features": []}
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(collection))
        return 0

    features = build_n1_overlay_features(
        ranking=ranking, snapshot=snapshot, max_features=max_features
    )
    collection = {"type": "FeatureCollection", "features": features}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(collection, indent=2))
    return len(features)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export GeoJSON overlay from an episode's last N-1 contingency step.",
    )
    parser.add_argument("episode_log", type=Path, help="Path to episode_*.jsonl")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Output .geojson path (e.g. platform/atlas/public/overlays/run.geojson)",
    )
    parser.add_argument(
        "--bundle-root",
        type=Path,
        default=None,
        help="Override snapshot bundle directory (default: $GRIDAGENT_DATA_ROOT/bundle)",
    )
    parser.add_argument(
        "--max-features",
        type=int,
        default=40,
        help="Cap ranking rows mapped to lines (default: 40)",
    )
    args = parser.parse_args(argv)
    try:
        n = write_n1_overlay_from_episode(
            args.episode_log,
            args.output,
            bundle_root=args.bundle_root,
            max_features=args.max_features,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(f"Wrote {n} features → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
