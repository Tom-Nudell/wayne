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
USGS_USWTDB = Source(
    name="usgs_uswtdb",
    url="https://energy.usgs.gov/uswtdb/",
    license="US-PD",
    notes="US Wind Turbine Database — per-turbine locations + specs; eia_id joins to EIA-860",
)
USGS_USPVDB = Source(
    name="usgs_uspvdb",
    url="https://energy.usgs.gov/uspvdb/",
    license="US-PD",
    notes="US Large-Scale Solar PV Database — per-facility footprints + specs",
)
OPEN_METEO = Source(
    name="open_meteo",
    url="https://open-meteo.com/",
    license="CC-BY-4.0",
    notes="NWP forecast aggregator; attribution required for redistribution",
)

ELEXON_BMRS = Source(
    name="elexon_bmrs",
    url="https://bmrs.elexon.co.uk/",
    license="Elexon-Open-Data",
    notes="Insights Solution API; contains BSC data © Elexon Limited — attribution required",
)
NESO_OPEN_DATA = Source(
    name="neso_open_data",
    url="https://www.neso.energy/data-portal",
    license="NESO-Open-Licence",
    notes="CKAN portal; open licence, attribution required",
)
NG_ESO_CARBON_INTENSITY = Source(
    name="carbon_intensity",
    url="https://carbonintensity.org.uk/",
    license="CC-BY-4.0",
    notes="National Grid ESO GB carbon intensity, half-hourly forecast + actual",
)
PV_LIVE = Source(
    name="pv_live",
    url="https://www.solar.sheffield.ac.uk/pvlive/",
    license="Attribution",
    notes="University of Sheffield GB solar outturn estimates; attribution required",
)
ENTSOE = Source(
    name="entsoe",
    url="https://transparency.entsoe.eu/",
    license="ENTSOE-API-Terms",
    notes="Transparency Platform; free token required (ENTSOE_API_TOKEN); attribution required",
)
ECB_FX = Source(
    name="ecb_fx",
    url="https://www.ecb.europa.eu/stats/eurofxref/",
    license="Attribution",
    notes="Euro foreign exchange reference rates; free with attribution",
)

# Sources deliberately deferred until we can confirm a fully-open subset:
#   * Global Energy Monitor — tiered; some trackers require commercial licensing.
# GB/EU sources above carry their own open-but-bespoke licences (Elexon Open
# Data, NESO Open Licence, ENTSO-E API terms) — all permit redistribution
# with attribution; attribution strings surface via these Source records.


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)
