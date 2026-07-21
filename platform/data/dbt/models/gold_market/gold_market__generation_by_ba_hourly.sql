-- Gold market mart: hourly generation by BA + fuel type.
--
-- Populated from EIA-930 via PUDL (all US BAs, hourly). GridStatus
-- fuel-mix partitions can be unioned in later where finer intra-ISO
-- resolution is needed; the EIA-930 series is the national baseline.
-- Schema matches ``gold_market__load_hourly`` on the time/BA keys so
-- ``query_grid`` can join them for net-load calculations.

select
    balancing_authority,
    interval_start_utc,
    fuel_type,
    generation_mwh,
    source,
    license
from {{ ref('silver_pudl__eia930_generation') }}
