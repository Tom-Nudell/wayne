"""GridStatus bronze loader.

GridStatus (gridstatus.io) is the historical + real-time LMP / load /
generation-mix API across all seven US ISOs. We pull each dataset as daily
parquet partitions into bronze; silver dbt models union them into
``gold_market__lmp_hourly`` / ``gold_market__load_hourly`` /
``gold_market__generation_by_ba_hourly``.
"""

from __future__ import annotations

from .bronze import DATASETS, ISOS, GridStatusPartition, fetch_day

__all__ = ["DATASETS", "ISOS", "GridStatusPartition", "fetch_day"]
