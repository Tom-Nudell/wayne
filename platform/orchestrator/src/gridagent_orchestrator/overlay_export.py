"""Build GeoJSON overlays from episode logs for the atlas display terminal.

Layout written by ``write_episode_overlays()``:
  {overlay_dir}/{episode_id}/n1_contingency.geojson
  {overlay_dir}/{episode_id}/provenance.json

The provenance sidecar lists every overlay file so the atlas JS knows what
to fetch without directory listing.

Legacy function ``write_n1_overlay_from_episode()`` (flat file output) is
kept for the CLI ``-o`` flag. New code should use ``write_episode_overlays()``.
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


def _parse_log(log_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _iter_steps(log_path: Path) -> list[dict[str, Any]]:
    return [r for r in _parse_log(log_path) if r.get("event") == "step"]


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


# ---------------------------------------------------------------------------
# General overlay / provenance helpers
# ---------------------------------------------------------------------------


def write_geojson_overlay(
    episode_id: str,
    tool_name: str,
    features: list[dict[str, Any]],
    metadata: dict[str, Any],
    *,
    overlay_dir: Path,
) -> Path:
    """Write a FeatureCollection to ``{overlay_dir}/{episode_id}/{tool_name}.geojson``.

    ``metadata`` is embedded in the FeatureCollection under the ``metadata`` key
    so the atlas can surface it in popovers without fetching a separate file.
    Returns the path written.
    """
    ep_dir = overlay_dir / episode_id
    ep_dir.mkdir(parents=True, exist_ok=True)
    out = ep_dir / f"{tool_name}.geojson"
    collection: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": metadata,
    }
    out.write_text(json.dumps(collection, indent=2))
    return out


def write_provenance(
    episode_id: str,
    *,
    question: str,
    started_at: str,
    tools_called: list[str],
    overlays: list[str],
    data_version: str = "",
    model: str = "",
    overlay_dir: Path,
) -> Path:
    """Write ``{overlay_dir}/{episode_id}/provenance.json``.

    ``overlays`` lists every ``.geojson`` filename in this episode directory
    so the atlas can fetch them without a directory listing API.
    """
    ep_dir = overlay_dir / episode_id
    ep_dir.mkdir(parents=True, exist_ok=True)
    out = ep_dir / "provenance.json"
    doc: dict[str, Any] = {
        "episode_id": episode_id,
        "question": question,
        "started_at": started_at,
        "tools_called": tools_called,
        "overlays": overlays,
        "data_version": data_version,
        "model": model,
    }
    out.write_text(json.dumps(doc, indent=2))
    return out


# ---------------------------------------------------------------------------
# High-level entry points
# ---------------------------------------------------------------------------


def write_episode_overlays(
    episode_log: Path,
    overlay_dir: Path,
    *,
    bundle_root: Path | None = None,
    max_features: int = 40,
) -> tuple[int, str]:
    """Parse ``episode_log`` and write all spatial overlays + provenance.

    Output layout::

        {overlay_dir}/{episode_id}/n1_contingency.geojson   (if N-1 ran)
        {overlay_dir}/{episode_id}/provenance.json

    Returns ``(total_feature_count, episode_id)``.
    """
    bundle_root = bundle_root or _bundle_root()
    records = _parse_log(episode_log)

    start_rec = next((r for r in records if r.get("event") == "start"), None)
    if start_rec is None:
        raise ValueError(f"No start record in {episode_log}")

    episode_id: str = start_rec.get("episode_id") or episode_log.stem.removeprefix("episode_")
    goal: str = start_rec.get("goal", "")
    started_at: str = str(start_rec.get("ts", ""))

    steps = [r for r in records if r.get("event") == "step"]
    tools_called = [s.get("tool", "") for s in steps if s.get("tool")]

    overlays_written: list[str] = []
    total_features = 0

    # N-1 contingency — use the last step in case the agent retried.
    for rec in reversed(steps):
        if rec.get("tool") != "run_n1_contingency":
            continue
        args = rec.get("arguments") or {}
        scenario_id = args.get("scenario_id")
        if not scenario_id:
            break
        value = rec.get("value") or {}
        ranking = value.get("ranking") or []
        if not ranking:
            break
        try:
            scenario = load_scenario(str(scenario_id))
            snapshot_id = scenario.get("snapshot_id")
            if not snapshot_id:
                candidates = sorted(
                    (p for p in bundle_root.iterdir() if p.is_dir() and p.name.startswith("snapshot_") and (p / "buses.parquet").exists()),
                    reverse=True,
                )
                if not candidates:
                    break
                snapshot_id = candidates[0].name
            snapshot = Snapshot.at(bundle_root / snapshot_id)
            features = build_n1_overlay_features(
                ranking=ranking, snapshot=snapshot, max_features=max_features
            )
            write_geojson_overlay(
                episode_id,
                "n1_contingency",
                features,
                {
                    "description": "N-1 contingency overloads",
                    "units": "% loading",
                    "source_table": "branches",
                },
                overlay_dir=overlay_dir,
            )
            overlays_written.append("n1_contingency.geojson")
            total_features += len(features)
        except Exception:
            pass
        break

    model = os.environ.get("GRIDAGENT_LLM_MODEL", "gemma4:e12b")
    write_provenance(
        episode_id,
        question=goal,
        started_at=started_at,
        tools_called=tools_called,
        overlays=overlays_written,
        model=model,
        overlay_dir=overlay_dir,
    )

    return total_features, episode_id


def write_n1_overlay_from_episode(
    episode_log: Path,
    out_path: Path,
    *,
    bundle_root: Path | None = None,
    max_features: int = 40,
) -> int:
    """Parse ``episode_log`` and write a FeatureCollection to ``out_path``.

    Legacy flat-file API kept for the CLI ``-o`` flag and backward compat.
    New code should use ``write_episode_overlays()``.

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
            (p for p in bundle_root.iterdir() if p.is_dir() and p.name.startswith("snapshot_") and (p / "buses.parquet").exists()),
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
        default=None,
        help="Output .geojson path (flat file). Mutually exclusive with --overlay-dir.",
    )
    parser.add_argument(
        "--overlay-dir",
        type=Path,
        default=None,
        help=(
            "Write directory-per-episode layout to this dir "
            "(recommended; use with the atlas ?episode=<id> seam)."
        ),
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

    if args.overlay_dir:
        try:
            n, episode_id = write_episode_overlays(
                args.episode_log,
                args.overlay_dir,
                bundle_root=args.bundle_root,
                max_features=args.max_features,
            )
        except (ValueError, FileNotFoundError) as exc:
            print(exc, file=sys.stderr)
            return 2
        ep_dir = args.overlay_dir / episode_id
        print(f"Wrote {n} features → {ep_dir}/  (open atlas with ?episode={episode_id})")
        return 0

    if args.output is None:
        print("Error: provide --output or --overlay-dir", file=sys.stderr)
        return 2

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
