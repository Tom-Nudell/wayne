-- Gold market mart: hourly LMPs by ISO node.
--
-- Stub for the first slice; the column contract is what tools and the atlas
-- will bind to. Real rows arrive once the GridStatus bronze loader lands.
-- Defining the table now lets dbt tests (and downstream agent tools)
-- exercise against an empty-but-typed table.

select
    cast(null as varchar) as iso,
    cast(null as varchar) as node,
    cast(null as timestamp) as interval_start_utc,
    cast(null as double) as lmp_usd_per_mwh,
    cast(null as double) as energy_component,
    cast(null as double) as congestion_component,
    cast(null as double) as loss_component,
    cast(null as varchar) as source,
    cast(null as varchar) as license
where 1 = 0
