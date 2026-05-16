"""Command-line entrypoint for ad-hoc ETL runs.

Subcommands:

* ``ingest pudl``            — PUDL parquet release → bronze.
* ``ingest rts_gmlc``        — RTS-GMLC source CSVs → bronze.
* ``ingest gridstatus``      — GridStatus daily CSVs → bronze (one ISO, one day).
* ``ingest lbnl``            — LBNL Queued Up workbook → bronze.
* ``ingest hifld``           — HIFLD archived substations + transmission → bronze.
* ``ingest osm``             — OSM ``power=*`` Overpass query for a region → bronze.
* ``ingest pypsa_usa PATH``  — adopt a pre-built ``elec.nc`` into bronze.
* ``snapshot rts``           — assemble a Snapshot bundle from RTS-GMLC bronze.
* ``dbt <subcommand>``       — run dbt against the in-tree project.
* ``bundle [atlas-public]``  — export warehouse → ``bundle.duckdb`` + PMTiles;
                               optional ``--atlas-public DIR`` drops the bundle
                               and tiles into the atlas frontend's ``public/``.
* ``list``                   — show what's in BUNDLE.

Heavier orchestration (silver dbt models, gold marts, scheduling) lives in
the Dagster job graph; the CLI is for the bring-up path and developer loops.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gridagent_data.paths import BUNDLE, WAREHOUSE


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


def cmd_ingest_gridstatus(iso: str, dataset: str, day: str) -> int:
    from datetime import date as _date

    from gridagent_data.sources.gridstatus import GridStatusPartition, fetch_day

    part = GridStatusPartition(dataset=dataset, iso=iso, day=_date.fromisoformat(day))
    m = fetch_day(part)
    print(f"GridStatus {part.iso}/{part.dataset}/{part.day}: {m['bytes']} bytes → {m['path']}")
    return 0


def cmd_refresh_daily(
    *,
    day: str | None,
    isos: list[str] | None,
    datasets: list[str] | None,
    warehouse: Path,
    out_dir: Path,
    atlas_public: Path | None,
    include_gridstatus: bool = True,
    include_osm: bool = True,
    include_queue_feed: bool = True,
) -> int:
    """Daily refresh for atlas-facing data.

    Flow:
      1) Optionally ingest GridStatus partitions for one day across ISOs/datasets.
      2) Rebuild dbt models (run-only to avoid test-gating the refresh loop).
      3) Export bundle.duckdb + PMTiles and mirror into atlas public dir.
    """
    selected_day = day or (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

    if include_gridstatus:
        from gridagent_data.sources.gridstatus.bronze import DATASETS, ISOS, GridStatusPartition, fetch_day

        selected_isos = [s.strip().lower() for s in (isos or list(ISOS)) if s.strip()]
        selected_datasets = [d.strip().lower() for d in (datasets or list(DATASETS)) if d.strip()]

        print(f"Refreshing GridStatus for {selected_day} (isos={selected_isos}, datasets={selected_datasets})")
        for dataset in selected_datasets:
            for iso in selected_isos:
                part = GridStatusPartition(dataset=dataset, iso=iso, day=datetime.fromisoformat(selected_day).date())
                try:
                    m = fetch_day(part)
                    print(f"  · {iso}/{dataset}: {m['bytes']} bytes → {m['path']}")
                except Exception as exc:
                    # Keep refresh resilient: one failed partition should not block atlas rebuild.
                    print(f"  ! {iso}/{dataset}: skipped ({exc})", file=sys.stderr)
    else:
        print("Skipping GridStatus ingest (--no-gridstatus).")

    if include_osm:
        print("Refreshing OSM regions (power + gas pipelines).")
        from gridagent_data.sources.osm import REGIONS, fetch_region

        for region in REGIONS:
            try:
                m = fetch_region(region)
                print(
                    f"  · OSM {region.name}: {m['bytes']} bytes, "
                    f"elements={m.get('element_counts', {})} → {m['path']}"
                )
            except Exception as exc:
                print(f"  ! OSM {region.name}: skipped ({exc})", file=sys.stderr)
    else:
        print("Skipping OSM ingest (--no-osm).")

    if include_queue_feed:
        from gridagent_data.sources.queue_feed import fetch_csv_feed, fetch_interconnection_fyi_public
        provider = os.environ.get("GRIDAGENT_QUEUE_PROVIDER", "csv_url").strip().lower()

        try:
            if provider == "interconnection_fyi_public":
                m = fetch_interconnection_fyi_public()
            else:
                m = fetch_csv_feed()
            print(
                f"Queue feed: {m['bytes']} bytes → {m['path']}"
                + (f" (url={m['url']})" if m.get("url") else "")
                + (f" (provider={m['provider']})" if m.get("provider") else "")
            )
        except Exception as exc:
            print(f"  ! queue_feed: skipped ({exc})", file=sys.stderr)
    else:
        print("Skipping queue feed ingest (--no-queue-feed).")

    rc = cmd_dbt("run", [])
    if rc != 0:
        return rc
    return cmd_bundle(warehouse=warehouse, out_dir=out_dir, atlas_public=atlas_public)


def cmd_ingest_lbnl(source_path: str | None = None) -> int:
    from gridagent_data.sources.lbnl import adopt_release, fetch_release

    if source_path:
        m = adopt_release(source_path)
        print(f"LBNL Queued Up (manual): {m['bytes']} bytes → {m['path']}")
        return 0
    m = fetch_release()
    print(f"LBNL Queued Up release {m['release_year']}: {m['bytes']} bytes → {m['path']}")
    return 0


def cmd_ingest_hifld() -> int:
    from gridagent_data.sources.hifld import LAYERS, fetch_layer

    for layer in LAYERS:
        m = fetch_layer(layer)
        print(f"HIFLD {layer.name}: {m['bytes']} bytes → {m['path']}")
    return 0


def cmd_ingest_osm(region_name: str | None) -> int:
    from gridagent_data.sources.osm import REGIONS, fetch_region

    selected = (
        [r for r in REGIONS if r.name == region_name] if region_name else list(REGIONS)
    )
    if not selected:
        print(f"Unknown OSM region '{region_name}'. Known: {[r.name for r in REGIONS]}")
        return 2
    for region in selected:
        m = fetch_region(region)
        print(
            f"OSM {region.name}: {m['bytes']} bytes, "
            f"elements={m.get('element_counts', {})} → {m['path']}"
        )
    return 0


def cmd_ingest_queue_feed(source_url: str | None) -> int:
    from gridagent_data.sources.queue_feed import fetch_csv_feed, fetch_interconnection_fyi_public

    provider = os.environ.get("GRIDAGENT_QUEUE_PROVIDER", "csv_url").strip().lower()
    if provider == "interconnection_fyi_public":
        m = fetch_interconnection_fyi_public()
    else:
        m = fetch_csv_feed(source_url)
    print(
        f"Queue feed: {m['bytes']} bytes → {m['path']}"
        + (f" (url={m['url']})" if m.get("url") else "")
        + (f" (provider={m['provider']})" if m.get("provider") else "")
    )
    return 0


def cmd_ingest_pypsa_usa(source_path: str | None, *, label: str) -> int:
    from gridagent_data.sources.pypsa_usa import adopt_elec_nc, fetch_elec_nc

    if not source_path:
        print("ingest pypsa_usa requires a path to elec.nc (or a URL with --url).")
        return 2
    if source_path.startswith(("http://", "https://")):
        m = fetch_elec_nc(source_path, label=label)
    else:
        m = adopt_elec_nc(source_path, label=label)
    print(f"PyPSA-USA elec.nc ({m['ingest_mode']}): {m['bytes']} bytes → {m['path']}")
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
    project lives at ``platform/data/dbt/`` and carries its own profile.
    """
    project_dir = Path(__file__).resolve().parents[2] / "dbt"
    env = os.environ.copy()
    env.setdefault("DBT_PROFILES_DIR", str(project_dir))
    cmd = ["dbt", subcommand, "--project-dir", str(project_dir), *extra]
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.call(cmd, env=env)


def cmd_bundle(
    warehouse: Path,
    out_dir: Path,
    *,
    atlas_public: Path | None = None,
) -> int:
    """Run both atlas exporters against ``warehouse`` into ``out_dir``.

    Produces ``bundle.duckdb`` (for DuckDB-WASM) and one PMTiles file per
    kind (for MapLibre). ``atlas_public`` is a convenience: after the
    exporters write into ``out_dir`` we also copy the artifacts into the
    Vite dev server's ``public/`` so the atlas picks them up on reload.
    """
    from gridagent_data.exporters import to_duckdb, to_pmtiles

    warehouse = Path(warehouse)
    out_dir = Path(out_dir)
    if not warehouse.is_file():
        print(f"Warehouse not found at {warehouse}", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    bundle_path = out_dir / "bundle.duckdb"
    to_duckdb.export(warehouse, bundle_path)
    print(f"Wrote {bundle_path}")

    tile_dir = out_dir / "tiles"
    tile_results = to_pmtiles.export(warehouse, tile_dir)
    for r in tile_results:
        suffix = r.pmtiles_path.name if r.pmtiles_path else "(geojson only; tippecanoe not on PATH)"
        print(f"  · {r.kind}: {r.feature_count} features → {suffix}")

    if atlas_public is not None:
        atlas_public = atlas_public.resolve()
        tile_dir_resolved = tile_dir.resolve()
        try:
            atlas_public.relative_to(tile_dir_resolved)
            # atlas_public is inside tile_dir — almost certainly a mistake
            # (e.g. --atlas-public passed the tiles symlink instead of atlas/public/)
            print(
                f"error: --atlas-public ({atlas_public}) is inside the tile output "
                f"directory ({tile_dir_resolved}).\n"
                f"Pass the Vite public/ directory instead, e.g. platform/atlas/public/",
                file=sys.stderr,
            )
            return 2
        except ValueError:
            pass  # not a subdirectory — fine
        atlas_public.mkdir(parents=True, exist_ok=True)
        to_duckdb.copy_to_atlas_public(bundle_path, atlas_public)
        # Mirror tiles alongside the bundle so the atlas's ``VITE_TILE_BASE=/tiles``
        # default resolves without further configuration.
        tile_public = atlas_public / "tiles"
        tile_public.mkdir(parents=True, exist_ok=True)
        import shutil as _shutil
        for r in tile_results:
            for src in filter(None, [r.geojson_path, r.pmtiles_path]):
                if src.is_file():
                    _shutil.copy2(src, tile_public / src.name)
        print(f"Copied bundle + tiles into {atlas_public}")

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
    ing.add_argument(
        "source",
        choices=["pudl", "rts_gmlc", "gridstatus", "lbnl", "hifld", "osm", "pypsa_usa", "queue_feed"],
    )
    ing.add_argument("path", nargs="?", help="Source path / URL (for pypsa_usa).")
    ing.add_argument("--iso", default="ercot", help="ISO code (gridstatus only).")
    ing.add_argument(
        "--dataset", default="lmp_hourly", help="GridStatus dataset slug."
    )
    ing.add_argument("--day", default=None, help="ISO date (gridstatus only).")
    ing.add_argument("--region", default=None, help="OSM region name (osm only).")
    ing.add_argument(
        "--label", default="default", help="Sub-label under bronze (pypsa_usa only)."
    )

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

    bun = sub.add_parser(
        "bundle",
        help="Export warehouse → bundle.duckdb + PMTiles for the atlas frontend.",
    )
    bun.add_argument(
        "--warehouse",
        default=str(WAREHOUSE),
        help="Path to the dbt-built warehouse.duckdb.",
    )
    bun.add_argument(
        "--out",
        default=None,
        help="Output directory (default: $DATA_ROOT/bundle/snapshot_latest).",
    )
    bun.add_argument(
        "--atlas-public",
        default=None,
        help="Optional path to platform/atlas/public/ to mirror artifacts.",
    )

    sub.add_parser("list", help="List snapshot bundles.")

    ref = sub.add_parser(
        "refresh-daily",
        help="Daily atlas refresh: optional GridStatus ingest + dbt run + bundle export.",
    )
    ref.add_argument(
        "--day",
        default=None,
        help="UTC day YYYY-MM-DD (default: yesterday UTC).",
    )
    ref.add_argument(
        "--isos",
        default="",
        help="Comma-separated ISO list (default: all known ISOs).",
    )
    ref.add_argument(
        "--datasets",
        default="",
        help="Comma-separated dataset list (default: lmp_hourly,load_hourly,fuel_mix_hourly).",
    )
    ref.add_argument(
        "--no-gridstatus",
        action="store_true",
        help="Skip GridStatus ingest and only rebuild/export from existing bronze data.",
    )
    ref.add_argument(
        "--no-osm",
        action="store_true",
        help="Skip OSM ingest and only rebuild/export from existing bronze data.",
    )
    ref.add_argument(
        "--no-queue-feed",
        action="store_true",
        help="Skip queue feed ingest and only rebuild/export from existing bronze data.",
    )
    ref.add_argument(
        "--warehouse",
        default=str(WAREHOUSE),
        help="Path to warehouse.duckdb (dbt target).",
    )
    ref.add_argument(
        "--out",
        default=None,
        help="Output bundle directory (default: $DATA_ROOT/bundle/snapshot_latest).",
    )
    ref.add_argument(
        "--atlas-public",
        default=None,
        help="Optional path to platform/atlas/public/ to mirror artifacts.",
    )

    args = parser.parse_args(argv)
    if args.cmd == "ingest" and args.source == "pudl":
        return cmd_ingest_pudl()
    if args.cmd == "ingest" and args.source == "rts_gmlc":
        return cmd_ingest_rts()
    if args.cmd == "ingest" and args.source == "gridstatus":
        if not args.day:
            parser.error("ingest gridstatus requires --day YYYY-MM-DD")
        return cmd_ingest_gridstatus(args.iso, args.dataset, args.day)
    if args.cmd == "ingest" and args.source == "lbnl":
        return cmd_ingest_lbnl(args.path)
    if args.cmd == "ingest" and args.source == "hifld":
        return cmd_ingest_hifld()
    if args.cmd == "ingest" and args.source == "osm":
        return cmd_ingest_osm(args.region)
    if args.cmd == "ingest" and args.source == "pypsa_usa":
        return cmd_ingest_pypsa_usa(args.path, label=args.label)
    if args.cmd == "ingest" and args.source == "queue_feed":
        return cmd_ingest_queue_feed(args.path)
    if args.cmd == "snapshot" and args.from_source == "rts":
        return cmd_snapshot_rts()
    if args.cmd == "dbt":
        return cmd_dbt(args.subcommand, args.extra or [])
    if args.cmd == "bundle":
        out_dir = Path(args.out) if args.out else BUNDLE / "snapshot_latest"
        atlas_public = Path(args.atlas_public) if args.atlas_public else None
        return cmd_bundle(Path(args.warehouse), out_dir, atlas_public=atlas_public)
    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "refresh-daily":
        out_dir = Path(args.out) if args.out else BUNDLE / "snapshot_latest"
        atlas_public = Path(args.atlas_public) if args.atlas_public else None
        isos = [s for s in args.isos.split(",") if s.strip()] if args.isos else None
        datasets = [d for d in args.datasets.split(",") if d.strip()] if args.datasets else None
        return cmd_refresh_daily(
            day=args.day,
            isos=isos,
            datasets=datasets,
            warehouse=Path(args.warehouse),
            out_dir=out_dir,
            atlas_public=atlas_public,
            include_gridstatus=not args.no_gridstatus,
            include_osm=not args.no_osm,
            include_queue_feed=not args.no_queue_feed,
        )
    parser.error(f"Unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
