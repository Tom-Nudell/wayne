-- Gold market mart: hourly generation by BA + fuel type.
--
-- Stub for the first slice. Populated from EIA-930 (BA-level) plus
-- GridStatus (ISO-level, when finer resolution is needed). The schema
-- intentionally matches ``gold_market__load_hourly`` on the time/BA keys
-- so ``query_grid`` can join them for net-load calculations.

select
    cast(null as varchar) as balancing_authority,
    cast(null as timestamp) as interval_start_utc,
    cast(null as varchar) as fuel_type,
    cast(null as double) as generation_mwh,
    cast(null as varchar) as source,
    cast(null as varchar) as license
where 1 = 0
