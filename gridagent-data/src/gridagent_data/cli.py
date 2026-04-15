"""Command-line entrypoint for ad-hoc ETL runs.

Subcommands:

* ``ingest pudl``      — fetch every table listed in ``sources.pudl.bronze.TABLES``.
* ``ingest rts_gmlc``  — fetch the RTS-GMLC source CSVs.
* ``snapshot rts``     — assemble the canonical Snapshot bundle from RTS-GMLC bronze.
* ``list``             — show what's in BUNDLE.

Heavier orchestration (silver dbt models, gold marts, scheduling) lives in
the Dagster job graph; the CLI is for the bring-up path and developer loops.
"""

from __future__ import annotations

import argparse
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

    sub.add_parser("list", help="List snapshot bundles.")

    args = parser.parse_args(argv)
    if args.cmd == "ingest" and args.source == "pudl":
        return cmd_ingest_pudl()
    if args.cmd == "ingest" and args.source == "rts_gmlc":
        return cmd_ingest_rts()
    if args.cmd == "snapshot" and args.from_source == "rts":
        return cmd_snapshot_rts()
    if args.cmd == "list":
        return cmd_list()
    parser.error(f"Unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
