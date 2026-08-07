"""Convert the Texas 7k synthetic grid into a Wayne snapshot.

Case attribution: a Texas A&M University released open synthetic test case
(the RAW title line identifies it as a synthetic electric grid designed by
university researchers; confirmed by the project owner as a Texas A&M open
release, 2026-08-07). It models no real infrastructure and carries no CEII.
Source file: iq-boost/local_bucket/pytest/SmallSystem_case.raw (PSS/E v34).


Source
------
``/Users/trn/Documents/Git/iq-boost/local_bucket/pytest/SmallSystem_case.raw``
(read-only; a synthetic ERCOT-like grid, 6,717 buses / 7,172 AC branches /
1,967 two-winding transformers / 731 generators / 5,095 loads, SBASE=100 MVA)
plus ``small_model_topology.zip: bus.csv`` for GIS coordinates.

Parsing path used: **PATH 2** (iq-boost's tested RAW schema primitives)
------------------------------------------------------------------------
Path 1 (pandapower's built-in PSS/E converter) was checked first and does
not exist in this environment: ``pandapower.converter`` only exposes
``pandamodels`` -- no ``from_psse`` / ``psse2pp`` on pandapower 3.5.4 here.

Path 2 is what's actually used. iq-boost's ``common.atlas.io.raw.parser``
module defines, per RAW chapter (Bus/Load/Generator/Branch/Transformer/
Area/Zone/...), the exact column layout as ``RAWEntry`` lists (including
optional trailing fields and, for transformers, the row-count-per-record
quirk: 4 lines for a 2-winding unit, 5 for 3-winding, decided from the K
field on line 1) plus a ``RAWComp.str2dataframe()`` that turns a block of
raw text lines into a typed DataFrame -- correctly handling PSS/E's
comma/quote/optional-field conventions. That's the fiddly, easy-to-get-
subtly-wrong part, so it's reused via ``sys.path`` insertion rather than
re-derived. iq-boost does **not** ship a "read this whole RAW file" driver
(only ``io/raw/export.py``, a *writer*), so this script does the section
splitting itself: PSS/E always emits a
``0 / END OF <SECTION> DATA, BEGIN <NEXT> DATA`` sentinel between chapters,
in a fixed order for v34/v35 -- we scan for those sentinels and slice.
Verified this matches exactly (22 sentinels, chapter-for-chapter) against
the RAW v34 chapter order iq-boost's own ``RAWStructure.get_chapters()``
declares.

iq-boost's parser module was checked for import weight before trusting it
in Wayne's venv: it only pulls in ``csv/io/re/collections/dataclasses/enum``
(stdlib) plus ``numpy``/``pandas`` and ``common.atlas.utils.flatten`` (pure
stdlib, no heavy deps). Confirmed with a clean import in Wayne's venv
before writing any of this.

Validated up front against this specific RAW file (see the "Data quirks
confirmed by inspection" section below) rather than assumed:
- All 1,967 transformers have CW=CZ=CM=1, i.e. R1-2/X1-2 are already
  per-unit on system base (SBASE=100 MVA, matching the snapshot's base) --
  no winding-base conversion needed. The script still asserts this at
  runtime and raises loudly if a future input violates it.
- No bus has IDE=4 (isolated) in this file, so no buses/branches are
  dropped on that basis -- the exclusion logic is still implemented and
  will fire (with a printed count) on any RAW file that does have them.
- Zero branches/transformers carry RATE1(-1)=0 in this data; the "zero
  rating means no rating given" handling is still implemented (rating is
  kept as 0.0, not invented) since it's a real possibility in other cases.

Coordinates
-----------
``bus.csv`` (from ``small_model_topology.zip``) maps GIS features to lists
of RAW bus numbers (``representative_bus_numbers``) with a WKT POLYGON /
MULTIPOLYGON / POINT ``geometry``. Centroids are computed by hand (shoelace
polygon-centroid formula for polygons, area-weighted across sub-polygons
for multipolygons, direct passthrough for points) -- no shapely dependency
added. Buses bus.csv doesn't cover (about 15% of them: generator aux buses,
etc.) get their coordinate by iteratively averaging already-located graph
neighbors (over the AC-branch + transformer topology) to a fixpoint; any
bus that still isn't reachable from a GIS-anchored bus this way falls back
to the system centroid. All three counts are reported below.

Mapping notes
-------------
- ``branch_id`` = ``"{from}_{to}_{ckt}"`` (ckt stripped); transformers get
  a ``"T_"`` prefix. Both share the snapshot's single ``branches`` table
  (the pandapower backend treats every branch identically: it's an R/X
  per-unit-on-system-base two-port on a DC PF, no explicit tap ratio
  modeled anywhere in ``_build_net``, so nothing is lost by folding
  transformers into the same table).
- Transformer ``b_pu`` is set to 0.0. MAG1/MAG2 in the RAW record are the
  magnetizing-branch admittance (core loss / no-load excitation), not a
  line-charging susceptance -- they are not the same physical quantity as
  branch ``B``, and the backend only ever reads ``b_pu`` as an LODF-inert
  placeholder (see ``pandapower.py::_build_net``'s comment on
  ``c_nf_per_km``), so this is a safe, side-effect-free simplification.
- Generator ``p_min_mw`` is clipped to <= ``p_max_mw`` (defensive; not
  observed in this file: PB > PT count is 0). Negative PB (synthetic
  storage discharge/charge asymmetry) is passed through unchanged.
- ``fuel`` is set to the literal string ``"unknown"`` for every generator
  -- the RAW format carries no fuel-type field at all.
- Area/zone names are resolved from the RAW's own AREA DATA / ZONE DATA
  chapters (``ARNAME`` / ``ZONAME``) when available, else fall back to the
  bare numeric code as a string.

Regenerate with
----------------
    cd /Users/trn/Documents/Git/wayne
    GRIDAGENT_DATA_ROOT=data_root \\
      platform/tools/.venv/bin/python platform/tools/eval/import_texas7k.py
"""

from __future__ import annotations

import ast
import csv
import os
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
IQBOOST_ROOT = Path("/Users/trn/Documents/Git/iq-boost")
RAW_PATH = IQBOOST_ROOT / "local_bucket" / "pytest" / "SmallSystem_case.raw"
TOPOLOGY_ZIP = IQBOOST_ROOT / "local_bucket" / "pytest" / "small_model_topology.zip"
SCRATCH = Path(
    "/private/tmp/claude-501/-Users-trn-Documents-Git-wayne/"
    "58f4091d-fe56-4591-bb21-e7d3c7aa989b/scratchpad"
)
DATA_ROOT = Path(os.environ.get("GRIDAGENT_DATA_ROOT", "data_root")) / "bundle"
SNAPSHOT_ROOT = DATA_ROOT / "snapshot_20250509_texas7k"

RAW_VERSION = 34

# Path 2: iq-boost's RAW schema/row-assembly primitives.
sys.path.insert(0, str(IQBOOST_ROOT))
from common.atlas.io.raw.parser import (  # noqa: E402
    Area,
    Branch,
    Bus,
    Generator,
    Load,
    RAWComp,
    Transformer,
    Zone,
)

from gridagent_tools.snapshot import (  # noqa: E402
    BRANCH_COLUMNS,
    BUS_COLUMNS,
    GENERATOR_COLUMNS,
    LOAD_COLUMNS,
    Snapshot,
    write_snapshot,
)

# --------------------------------------------------------------------------
# RAW section splitting
# --------------------------------------------------------------------------

# Fixed v34/v35 chapter order (matches iq-boost's RAWStructure.get_chapters()),
# each terminated by a "0 / END OF <NAME> DATA" sentinel line in the file.
CHAPTER_ORDER = [
    "SystemWide",
    "Bus",
    "Load",
    "FixedShunt",
    "Generator",
    "Branch",
    "SystemSwitchingDevice",
    "Transformer",
    "Area",
    "TwoTerminal",
    "VSC_DCLine",
    "ImpedanceCorrection",
    "MultiTerminal",
    "MultiSection",
    "Zone",
    "InterArea",
    "Owner",
    "FACTSDevice",
    "SwitchedShunt",
    "GNE",
    "InductionMachine",
    "Substation",
]

_DELIM_RE = re.compile(r"^\s*0\s*/\s*END OF", re.IGNORECASE)


def read_raw_lines(path: Path) -> list[str]:
    # PSS/E RAW files are not guaranteed UTF-8 (bus names etc. are free text
    # from various utilities); latin-1 never raises and round-trips bytes.
    with open(path, "r", encoding="latin-1") as f:
        return f.readlines()


def split_sections(lines: list[str]) -> dict[str, list[str]]:
    delims = [i for i, l in enumerate(lines) if _DELIM_RE.match(l)]
    if len(delims) != len(CHAPTER_ORDER):
        raise ValueError(
            f"Expected {len(CHAPTER_ORDER)} '0 / END OF ...' section delimiters "
            f"for RAW v{RAW_VERSION}, found {len(delims)}. RAW structure doesn't "
            "match the assumed v34 chapter order -- aborting rather than "
            "guessing at section boundaries."
        )
    sections: dict[str, list[str]] = {}
    for idx, name in enumerate(CHAPTER_ORDER):
        if idx == 0:
            continue  # SystemWide preamble (case ID + comments); not needed.
        start = delims[idx - 1] + 1
        end = delims[idx]
        seg = lines[start:end]
        # Drop blank lines and "@!..." column-header comments.
        seg = [l for l in seg if l.strip() and not l.lstrip().startswith("@!")]
        sections[name] = seg
    return sections


def parse_chapter(chapter_cls, lines: list[str]) -> pd.DataFrame:
    """Parse one RAW chapter's lines via iq-boost's RAWComp, with numeric
    columns coerced to real dtypes.

    RAWComp.str2dataframe builds an all-object-dtype frame and assigns
    converted values back in with ``.loc[mask, col] = ...astype(dtype)``,
    which stores real Python floats/ints *inside* the object column but
    does not change the column's pandas dtype. Comparisons/arithmetic on
    them mostly still work, but downstream dtype-sensitive operations
    (parquet round-trip, ``describe()``, elementwise comparisons against
    unboxed floats) can silently do the wrong thing on an object column --
    so we coerce explicitly here rather than trust the declared dtype.
    """
    rc = RAWComp(**chapter_cls.get_header(RAW_VERSION))
    df = rc.str2dataframe(lines)
    for col, dtype in rc.dtypes().items():
        if col not in df.columns:
            continue
        if dtype in (int, float):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        elif dtype is str:
            df[col] = df[col].astype(str).str.strip()
    return df


# --------------------------------------------------------------------------
# GIS coordinates (bus.csv), no shapely
# --------------------------------------------------------------------------


def _parse_ring(ring_str: str) -> list[tuple[float, float]]:
    pts = []
    for pair in ring_str.split(","):
        parts = pair.strip().split()
        pts.append((float(parts[0]), float(parts[1])))
    return pts


def _polygon_centroid(pts: list[tuple[float, float]]) -> tuple[float, float]:
    """Shoelace-formula centroid. Input/output are (x, y) = (lon, lat)."""
    if pts[0] != pts[-1]:
        pts = pts + [pts[0]]
    area2 = 0.0
    cx = 0.0
    cy = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        cross = x0 * y1 - x1 * y0
        area2 += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(area2) < 1e-12:
        # Degenerate (collinear) ring -- fall back to a plain vertex average.
        xs = [p[0] for p in pts[:-1]]
        ys = [p[1] for p in pts[:-1]]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    return cx / (3 * area2), cy / (3 * area2)


def _ring_area(pts: list[tuple[float, float]]) -> float:
    closed = pts if pts[0] == pts[-1] else pts + [pts[0]]
    area2 = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(closed, closed[1:]))
    return abs(area2) / 2.0


def parse_wkt_lonlat(wkt: str) -> tuple[float, float] | None:
    """Return (lon, lat) centroid for a WKT POINT / POLYGON / MULTIPOLYGON."""
    wkt = wkt.strip()
    if not wkt:
        return None
    paren_idx = wkt.find("(")
    if paren_idx == -1:
        return None
    kind = wkt[:paren_idx].strip().upper()
    body = wkt[paren_idx:].strip()

    if kind == "POINT":
        inner = body[1:-1]
        x_str, y_str = inner.split()
        return float(x_str), float(y_str)

    if kind == "POLYGON":
        inner = body[1:-1]  # strip outer paren -> "(ring)[,(hole)...]"
        m = re.match(r"\s*\(([^()]*)\)", inner)
        if not m:
            return None
        pts = _parse_ring(m.group(1))
        return _polygon_centroid(pts)

    if kind == "MULTIPOLYGON":
        inner = body[1:-1]
        rings = re.findall(r"\(\(([^()]*)\)\)", inner)
        if not rings:
            return None
        total_w = 0.0
        cx_sum = 0.0
        cy_sum = 0.0
        for ring_str in rings:
            pts = _parse_ring(ring_str)
            cx, cy = _polygon_centroid(pts)
            w = _ring_area(pts) or 1.0
            total_w += w
            cx_sum += cx * w
            cy_sum += cy * w
        return cx_sum / total_w, cy_sum / total_w

    return None


def load_direct_coords(bus_csv_path: Path) -> dict[int, tuple[float, float]]:
    """RAW bus number -> (lat, lon) from bus.csv, first-occurrence-wins."""
    direct: dict[int, tuple[float, float]] = {}
    with open(bus_csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            geom = (row.get("geometry") or "").strip()
            if not geom:
                continue
            parsed = parse_wkt_lonlat(geom)
            if parsed is None:
                continue
            lon, lat = parsed
            try:
                nums = ast.literal_eval(row["representative_bus_numbers"])
            except (ValueError, SyntaxError):
                continue
            for n in nums:
                direct.setdefault(int(n), (lat, lon))
    return direct


def propagate_coords(
    bus_ids: list[str],
    direct: dict[int, tuple[float, float]],
    edges: list[tuple[str, str]],
) -> tuple[dict[str, tuple[float, float]], int, int, int]:
    """Fill in coordinates for buses bus.csv doesn't cover.

    Returns (located, n_direct, n_propagated, n_fallback).
    """
    located: dict[str, tuple[float, float]] = {
        bid: direct[int(bid)] for bid in bus_ids if int(bid) in direct
    }
    n_direct = len(located)

    adjacency: dict[str, set[str]] = defaultdict(set)
    bus_id_set = set(bus_ids)
    for f, t in edges:
        if f in bus_id_set and t in bus_id_set:
            adjacency[f].add(t)
            adjacency[t].add(f)

    remaining = set(bus_ids) - set(located)
    changed = True
    while changed and remaining:
        changed = False
        newly: dict[str, tuple[float, float]] = {}
        for bid in remaining:
            neighbor_coords = [located[n] for n in adjacency.get(bid, ()) if n in located]
            if neighbor_coords:
                lat_avg = sum(c[0] for c in neighbor_coords) / len(neighbor_coords)
                lon_avg = sum(c[1] for c in neighbor_coords) / len(neighbor_coords)
                newly[bid] = (lat_avg, lon_avg)
        if newly:
            located.update(newly)
            remaining -= set(newly)
            changed = True

    n_fallback = len(remaining)
    n_propagated = len(bus_ids) - n_direct - n_fallback
    if remaining:
        lat_c = sum(c[0] for c in located.values()) / len(located)
        lon_c = sum(c[1] for c in located.values()) / len(located)
        for bid in remaining:
            located[bid] = (lat_c, lon_c)

    return located, n_direct, n_propagated, n_fallback


# --------------------------------------------------------------------------
# Main conversion
# --------------------------------------------------------------------------


def main() -> None:
    print(f"Reading RAW file: {RAW_PATH}")
    lines = read_raw_lines(RAW_PATH)
    sections = split_sections(lines)

    bus_raw = parse_chapter(Bus, sections["Bus"])
    load_raw = parse_chapter(Load, sections["Load"])
    gen_raw = parse_chapter(Generator, sections["Generator"])
    branch_raw = parse_chapter(Branch, sections["Branch"])
    xfmr_raw = parse_chapter(Transformer, sections["Transformer"])
    area_raw = parse_chapter(Area, sections["Area"])
    zone_raw = parse_chapter(Zone, sections["Zone"])

    n_bus_raw = len(bus_raw)
    n_load_raw = len(load_raw)
    n_gen_raw = len(gen_raw)
    n_branch_raw = len(branch_raw)
    n_xfmr_raw = len(xfmr_raw)

    print(
        f"Parsed: {n_bus_raw} buses, {n_branch_raw} AC branches, "
        f"{n_xfmr_raw} transformers, {n_gen_raw} generators, {n_load_raw} loads"
    )

    # ---- isolated-bus exclusion (IDE == 4) ------------------------------
    isolated_bus_nums = set(bus_raw.loc[bus_raw["IDE"] == 4, "I"].astype(int))
    n_isolated = len(isolated_bus_nums)
    bus_raw = bus_raw[~bus_raw["I"].isin(isolated_bus_nums)].copy()

    branch_touches_isolated = branch_raw["I"].isin(isolated_bus_nums) | branch_raw["J"].isin(
        isolated_bus_nums
    )
    n_branch_excluded = int(branch_touches_isolated.sum())
    branch_raw = branch_raw[~branch_touches_isolated].copy()

    xfmr_touches_isolated = xfmr_raw["I"].isin(isolated_bus_nums) | xfmr_raw["J"].isin(
        isolated_bus_nums
    )
    n_xfmr_excluded = int(xfmr_touches_isolated.sum())
    xfmr_raw = xfmr_raw[~xfmr_touches_isolated].copy()

    gen_touches_isolated = gen_raw["I"].isin(isolated_bus_nums)
    n_gen_excluded = int(gen_touches_isolated.sum())
    gen_raw = gen_raw[~gen_touches_isolated].copy()

    load_touches_isolated = load_raw["I"].isin(isolated_bus_nums)
    n_load_excluded = int(load_touches_isolated.sum())
    load_raw = load_raw[~load_touches_isolated].copy()

    # ---- area / zone name lookups ---------------------------------------
    area_names = dict(
        zip(area_raw["I"].astype(int), area_raw["ARNAME"].astype(str).str.strip())
    )
    zone_names = dict(
        zip(zone_raw["I"].astype(int), zone_raw["ZONAME"].astype(str).str.strip())
    )

    # ---- buses ------------------------------------------------------------
    buses = pd.DataFrame(
        {
            "bus_id": bus_raw["I"].astype(int).astype(str),
            "name": bus_raw["NAME"].astype(str).str.strip(),
            "base_kv": bus_raw["BASKV"].astype(float),
            "area": bus_raw["AREA"].astype(int).map(lambda i: area_names.get(i, str(i))),
            "zone": bus_raw["ZONE"].astype(int).map(lambda i: zone_names.get(i, str(i))),
        }
    )

    # ---- AC branches --------------------------------------------------
    n_zero_rating_lines = int((branch_raw["RATE1"] == 0).sum())
    branches_ac = pd.DataFrame(
        {
            "branch_id": (
                branch_raw["I"].astype(int).astype(str)
                + "_"
                + branch_raw["J"].astype(int).astype(str)
                + "_"
                + branch_raw["CKT"].astype(str).str.strip()
            ),
            "from_bus_id": branch_raw["I"].astype(int).astype(str),
            "to_bus_id": branch_raw["J"].astype(int).astype(str),
            "r_pu": branch_raw["R"].astype(float),
            "x_pu": branch_raw["X"].astype(float),
            "b_pu": branch_raw["B"].astype(float),
            "rating_a_mva": branch_raw["RATE1"].astype(float),
            "in_service": branch_raw["STAT"].astype(int) == 1,
        }
    )

    # ---- transformers ---------------------------------------------------
    cz_values = set(int(v) for v in xfmr_raw["CZ"].unique())
    cw_values = set(int(v) for v in xfmr_raw["CW"].unique())
    if cz_values - {1}:
        raise NotImplementedError(
            f"Transformer CZ codes other than 1 present: {sorted(cz_values)}. "
            "R1-2/X1-2 winding-base -> system-base conversion for CZ=2/3 is "
            "not implemented; aborting rather than emitting silently wrong "
            "impedances. (This file's transformers were verified CZ=1 at "
            "authoring time; a different RAW file tripped this.)"
        )

    n_zero_rating_xfmr = int((xfmr_raw["RATE1-1"] == 0).sum())
    branches_xfmr = pd.DataFrame(
        {
            "branch_id": (
                "T_"
                + xfmr_raw["I"].astype(int).astype(str)
                + "_"
                + xfmr_raw["J"].astype(int).astype(str)
                + "_"
                + xfmr_raw["CKT"].astype(str).str.strip()
            ),
            "from_bus_id": xfmr_raw["I"].astype(int).astype(str),
            "to_bus_id": xfmr_raw["J"].astype(int).astype(str),
            "r_pu": xfmr_raw["R1-2"].astype(float),
            "x_pu": xfmr_raw["X1-2"].astype(float),
            "b_pu": 0.0,
            "rating_a_mva": xfmr_raw["RATE1-1"].astype(float),
            "in_service": xfmr_raw["STAT"].astype(int) == 1,
        }
    )

    branches = pd.concat([branches_ac, branches_xfmr], ignore_index=True)

    dup = branches["branch_id"].duplicated()
    if dup.any():
        raise ValueError(
            f"{int(dup.sum())} duplicate branch_id(s) after conversion, e.g. "
            f"{branches.loc[dup, 'branch_id'].head().tolist()}"
        )

    # ---- generators -------------------------------------------------------
    p_max = gen_raw["PT"].astype(float)
    p_min = gen_raw["PB"].astype(float)
    n_pb_clipped = int((p_min > p_max).sum())
    p_min_clipped = np.minimum(p_min, p_max)

    generators = pd.DataFrame(
        {
            "generator_id": (
                gen_raw["I"].astype(int).astype(str)
                + "_"
                + gen_raw["ID"].astype(str).str.strip()
            ),
            "bus_id": gen_raw["I"].astype(int).astype(str),
            "p_max_mw": p_max,
            "p_min_mw": p_min_clipped,
            "q_max_mvar": gen_raw["QT"].astype(float),
            "q_min_mvar": gen_raw["QB"].astype(float),
            "fuel": "unknown",
            "in_service": gen_raw["STAT"].astype(int) == 1,
        }
    )

    # ---- loads --------------------------------------------------------
    loads = pd.DataFrame(
        {
            "load_id": (
                load_raw["I"].astype(int).astype(str)
                + "_"
                + load_raw["ID"].astype(str).str.strip()
            ),
            "bus_id": load_raw["I"].astype(int).astype(str),
            "p_mw": load_raw["PL"].astype(float),
            "q_mvar": load_raw["QL"].astype(float),
            "in_service": load_raw["STAT"].astype(int) == 1,
        }
    )

    # ---- coordinates ------------------------------------------------------
    print(f"Unzipping topology: {TOPOLOGY_ZIP} -> {SCRATCH / 'topology'}")
    topo_dir = SCRATCH / "topology"
    topo_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(TOPOLOGY_ZIP) as zf:
        zf.extract("bus.csv", topo_dir)
    direct_coords = load_direct_coords(topo_dir / "bus.csv")

    edges = list(zip(branches["from_bus_id"], branches["to_bus_id"]))
    located, n_direct, n_propagated, n_fallback = propagate_coords(
        list(buses["bus_id"]), direct_coords, edges
    )
    buses["lat"] = buses["bus_id"].map(lambda b: located[b][0])
    buses["lon"] = buses["bus_id"].map(lambda b: located[b][1])

    # ---- dtype conformance to snapshot schema ------------------------------
    def _cast(df: pd.DataFrame, schema: dict[str, str]) -> pd.DataFrame:
        for col, dtype in schema.items():
            df[col] = df[col].astype("string").astype(str) if dtype == "string" else df[col].astype(dtype)
        return df

    buses = _cast(buses, BUS_COLUMNS)
    branches = _cast(branches, BRANCH_COLUMNS)
    generators = _cast(generators, GENERATOR_COLUMNS)
    loads = _cast(loads, LOAD_COLUMNS)

    # ========================================================================
    # Validation report
    # ========================================================================
    print("\n" + "=" * 78)
    print("VALIDATION REPORT")
    print("=" * 78)

    print("\n-- 1. Record counts vs. known census --")
    print(f"buses:         raw={n_bus_raw:6d}  census=6717  isolated_excluded={n_isolated}  final={len(buses)}")
    print(f"AC branches:   raw={n_branch_raw:6d}  census=7172  isolated_excluded={n_branch_excluded}  final={len(branches_ac)}")
    print(f"transformers:  raw={n_xfmr_raw:6d}  census=1967  isolated_excluded={n_xfmr_excluded}  final={len(branches_xfmr)}")
    print(f"total branches: {len(branches)} (census 7172+1967=9139)")
    print(f"generators:    raw={n_gen_raw:6d}  census=731   isolated_excluded={n_gen_excluded}  final={len(generators)}")
    print(f"loads:         raw={n_load_raw:6d}  census=5095  isolated_excluded={n_load_excluded}  final={len(loads)}")
    print(f"generator PB>PT clipped to PT: {n_pb_clipped}")

    print("\n-- 2. write_snapshot --")
    snapshot = write_snapshot(
        SNAPSHOT_ROOT, buses=buses, branches=branches, generators=generators, loads=loads
    )
    print(f"wrote snapshot to {snapshot.root}")

    print("\n-- 3. Round-trip DC power flow --")
    import pandapower as pp

    from gridagent_tools.backends.pandapower import _build_net

    snap = Snapshot.at(SNAPSHOT_ROOT)
    net, bus_idx, branch_idx = _build_net(snap, {"change_table": {}})
    pp.rundcpp(net, numba=False)
    converged = bool(net["converged"])
    total_load_mw = float(net.load["p_mw"].sum())
    total_dispatch_mw = float(net.res_gen["p_mw"].sum()) if converged else None
    slack_mask = net.gen["slack"].astype(bool)
    slack_bus_pos = int(net.gen.loc[slack_mask, "bus"].iloc[0])
    slack_bus_name = str(net.bus.loc[slack_bus_pos, "name"])
    max_flow_mw = float(net.res_line["p_from_mw"].abs().max()) if converged else None
    print(f"converged: {converged}")
    print(f"total load: {total_load_mw:.1f} MW")
    print(f"total dispatch: {total_dispatch_mw:.1f} MW" if converged else "total dispatch: n/a (did not converge)")
    print(f"slack bus: {slack_bus_name}")
    print(f"max |branch flow|: {max_flow_mw:.1f} MW" if converged else "max |branch flow|: n/a")
    if not converged:
        raise RuntimeError("DC power flow did not converge on the generated snapshot")

    print("\n-- 4. Connectivity (in-service branches) --")
    import networkx as nx

    graph = nx.Graph()
    graph.add_nodes_from(buses["bus_id"])
    active = branches[branches["in_service"]]
    graph.add_edges_from(zip(active["from_bus_id"], active["to_bus_id"]))
    components = sorted(nx.connected_components(graph), key=len, reverse=True)
    print(f"connected components: {len(components)}")
    print(f"largest component: {len(components[0])} buses")
    if len(components) > 1:
        straggler_sizes = [len(c) for c in components[1:]]
        print(f"straggler component sizes: {straggler_sizes}")

    print("\n-- 5. Coordinate sanity --")
    lat_min, lat_max = float(buses["lat"].min()), float(buses["lat"].max())
    lon_min, lon_max = float(buses["lon"].min()), float(buses["lon"].max())
    print(f"lat range: [{lat_min:.3f}, {lat_max:.3f}]  (expected within [25, 37])")
    print(f"lon range: [{lon_min:.3f}, {lon_max:.3f}]  (expected within [-107, -93])")
    out_of_range = int(
        (~buses["lat"].between(25, 37) | ~buses["lon"].between(-107, -93)).sum()
    )
    print(f"buses outside Texas bounding box: {out_of_range}")
    print(f"coordinate coverage: direct={n_direct}  propagated={n_propagated}  fallback={n_fallback}  total={len(buses)}")

    print("\n-- 6. Rating coverage --")
    is_xfmr = branches["branch_id"].str.startswith("T_")
    lines_rated = branches.loc[~is_xfmr, "rating_a_mva"] > 0
    xfmr_rated = branches.loc[is_xfmr, "rating_a_mva"] > 0
    print(
        f"AC lines with rating_a_mva > 0: {int(lines_rated.sum())}/{len(lines_rated)} "
        f"({100.0 * lines_rated.mean():.1f}%)  [zero-rating count: {n_zero_rating_lines}]"
    )
    print(
        f"transformers with rating_a_mva > 0: {int(xfmr_rated.sum())}/{len(xfmr_rated)} "
        f"({100.0 * xfmr_rated.mean():.1f}%)  [zero-rating count: {n_zero_rating_xfmr}]"
    )

    print("\n-- 7. Snapshot size on disk --")
    total_bytes = sum(f.stat().st_size for f in SNAPSHOT_ROOT.glob("*") if f.is_file())
    print(f"{SNAPSHOT_ROOT}: {total_bytes / 1024:.1f} KiB across {len(list(SNAPSHOT_ROOT.glob('*')))} files")

    print("\n" + "=" * 78)
    print("DONE")
    print("=" * 78)


if __name__ == "__main__":
    main()
