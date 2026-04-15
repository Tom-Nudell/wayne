"""Command-line entrypoint for ad-hoc ETL runs.

Subcommands:

* ``ingest pudl``      — fetch every table listed in ``sources.pudl.bronze.TABLES``.
* ``ingest rts_gmlc``  — fetch the RTS-GMLC source CSVs.
* ``snapshot rts``     — assemble the canonical Snapshot bundle from RTS-GMLC bronze.
* ``dbt build``        — run the dbt silver→gold transforms over bronze parquet/CSV.
* ``list``             — show what's in BUNDLE.

Heavier orchestration (silver dbt models, gold marts, scheduling) lives in
the Dagster job graph; the CLI is for the bring-up path and developer loops.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from gridagent_data.paths import BUNDLE


def cmd_ingest_pudl() -> int:
    from gridagent_data.sources.pudl.bronze import TABLES, fetch_table

    print(f"Fetching {len(TABLES)} PUDL tables…")
    for tbl in TABLES:
        print(f"  · {tbl.name}", flush=True)
        manifest = fetch_table(tbl)
        print(f"    {manifest['bytes'] / 1e6:.1f} MB → {manifest['path']}")
    return 0


def cmd_ingest_rts() -> int:
    from gridagent_data.sources.rts_gmlc.bronze import fetch_all

    print("Fetching RTS-GMLC source CSVs…")
    for m in fetch_all():
        print(f"  · {m['file']}: {m['bytes']} bytes → {m['path']}")
    return 0


def cmd_snapshot_rts() -> int:
    from gridagent_data.exporters.to_snapshot import from_rts_gmlc

    snapshot = from_rts_gmlc()
    print(f"Wrote snapshot to {snapshot}")
    for f in sorted(snapshot.glob("*.parquet")):
        print(f"  · {f.name}")
    return 0


def cmd_dbt(subcommand: str, extra: list[str]) -> int:
    """Shell out to the dbt CLI against our project.

    We keep dbt as a subprocess rather than importing ``dbt-core``: the dbt
    Python API is deliberately unstable and mixing it into our package
    surface would force every caller to inherit its transitive deps. The
    project lives at ``gridagent-data/dbt/`` and carries its own profile.
    """
    project_dir = Path(__file__).resolve().parents[2] / "dbt"
    env = os.environ.copy()
    env.setdefault("DBT_PROFILES_DIR", str(project_dir))
    cmd = ["dbt", subcommand, "--project-dir", str(project_dir), *extra]
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.call(cmd, env=env)


def cmd_list() -> int:
    BUNDLE.mkdir(parents=True, exist_ok=True)
    snapshots = sorted(p for p in BUNDLE.iterdir() if p.is_dir() and p.name.startswith("snapshot_"))
    if not snapshots:
        print(f"No snapshots in {BUNDLE}")
        return 0
    for s in snapshots:
        print(s.name)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gridagent-data")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ing = sub.add_parser("ingest", help="Pull a source into bronze.")
    ing.add_argument("source", choices=["pudl", "rts_gmlc"])

    snap = sub.add_parser("snapshot", help="Build a canonical Snapshot bundle.")
    snap.add_argument("from_source", choices=["rts"])

    dbt = sub.add_parser(
        "dbt",
        help="Run a dbt command (build / run / test / compile / debug) against the project.",
    )
    dbt.add_argument(
        "subcommand",
        choices=["build", "run", "test", "compile", "debug", "parse"],
    )
    dbt.add_argument("extra", nargs=argparse.REMAINDER, help="Extra args forwarded to dbt.")

    sub.add_parser("list", help="List snapshot bundles.")

    args = parser.parse_args(argv)
    if args.cmd == "ingest" and args.source == "pudl":
        return cmd_ingest_pudl()
    if args.cmd == "ingest" and args.source == "rts_gmlc":
        return cmd_ingest_rts()
    if args.cmd == "snapshot" and args.from_source == "rts":
        return cmd_snapshot_rts()
    if args.cmd == "dbt":
        return cmd_dbt(args.subcommand, args.extra or [])
    if args.cmd == "list":
        return cmd_list()
    parser.error(f"Unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
