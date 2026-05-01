"""Provenance tagging for every record that flows through the ETL.

Every bronze record is annotated with the source it came from, when we
retrieved it, and what license its redistribution is governed by. These
columns are propagated through silver and into the gold marts so that the
atlas frontend (and any downstream consumer) can show attribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    license: str  # SPDX identifier or short tag (e.g. "ODbL-1.0", "US-PD", "CC-BY-4.0")
    notes: str = ""


# Canonical source registry. Add new sources here as they are introduced.
PUDL = Source(
    name="pudl",
    url="https://github.com/catalyst-cooperative/pudl",
    license="CC-BY-4.0",
    notes="Catalyst Cooperative ETL of EIA + FERC + EPA CEMS",
)
PYPSA_USA = Source(
    name="pypsa_usa",
    url="https://github.com/PyPSA/pypsa-usa",
    license="MIT",
)
GRIDSTATUS = Source(
    name="gridstatus",
    url="https://github.com/gridstatus/gridstatus",
    license="BSD-3-Clause",
    notes="ISO data; per-ISO terms apply to underlying tariffs and timeseries",
)
LBNL_QUEUED_UP = Source(
    name="lbnl_queued_up",
    url="https://emp.lbl.gov/queues",
    license="US-PD",
)
OSM = Source(
    name="osm",
    url="https://www.openstreetmap.org",
    license="ODbL-1.0",
    notes="Attribution required: '© OpenStreetMap contributors'",
)
HIFLD = Source(
    name="hifld",
    url="https://hifld-geoplatform.opendata.arcgis.com/",
    license="US-PD",
    notes="Archived 2022; superseded but still canonical for transmission topology",
)
NREL_SMART_DS = Source(
    name="nrel_smart_ds",
    url="https://www.nrel.gov/grid/smart-ds.html",
    license="US-PD",
)
EPRI_FEEDERS = Source(
    name="epri_feeders",
    url="https://sourceforge.net/projects/electricdss/",
    license="BSD-3-Clause",
    notes="OpenDSS is BSD-3; the test feeders are EPRI-published reference cases",
)

# Sources deliberately deferred until we can confirm a fully-open subset:
#   * Global Energy Monitor — tiered; some trackers require commercial licensing.
# v1 stays on US public-domain + CC-BY-4.0 + ODbL only.


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)
