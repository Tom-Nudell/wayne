"""Bundle exporters: turn gold marts into versioned, downstream-friendly artifacts.

Four exporters, one per consumer:

* :mod:`to_snapshot` — canonical parquet snapshot consumed by every backend
  (pandapower, Sienna, …). This is the contract every grid action binds to.
* :mod:`to_sienna` — MATPOWER ``.m`` for ``PowerSystems.jl`` ingestion
  (a Sienna-specific convenience; Sienna can also read the snapshot directly).
* :mod:`to_pmtiles` — PMTiles for the atlas frontend.
* :mod:`to_duckdb` — single DuckDB file for in-browser DuckDB-WASM queries.
"""
