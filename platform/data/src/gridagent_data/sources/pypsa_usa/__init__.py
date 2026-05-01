"""PyPSA-USA bronze loader.

PyPSA-USA produces a reconciled transmission network (``elec.nc``) via a
heavy Snakemake workflow that pulls EIA-860 / HIFLD / OSM / ATB. Running
the Snakemake pipeline inside our ETL would double-compile several GB of
intermediates; instead we ingest a pre-built ``elec.nc`` that the user
materialises out-of-band (either locally with ``snakemake -c4`` against
the upstream repo or downloaded from a publishing mirror) and copy it
into bronze with a recorded SHA-256.

Downstream silver models read the netCDF via ``pypsa.Network.import_*``.
"""

from __future__ import annotations

from .bronze import adopt_elec_nc, fetch_elec_nc

__all__ = ["adopt_elec_nc", "fetch_elec_nc"]
