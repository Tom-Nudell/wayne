"""PUDL bronze loader.

PUDL ships a complete parquet/SQLite ETL of EIA-860/861/923, EIA-930, EPA CEMS,
FERC-1/714 to Zenodo as nightly + tagged releases. We download the parquet
release rather than re-deriving from raw EIA forms.

For the first vertical slice we pull just one table: EIA-860 generators
(``core_eia860__scd_generators``). Other tables are added by extending
``TABLES`` and the bronze asset.
"""

from __future__ import annotations

from .bronze import TABLES, fetch_table

__all__ = ["TABLES", "fetch_table"]
