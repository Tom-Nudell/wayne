-- Gold market mart: hourly load by BA.
--
-- Stub for the first slice; the column contract is what tools and the atlas
-- will bind to. Real rows arrive once the GridStatus / EIA-930 bronze
-- loaders land. Defining the table now lets dbt tests and downstream agent
-- tools exercise against an empty-but-typed table.

select
    cast(null as varchar) as balancing_authority,
    cast(null as timestamp) as interval_start_utc,
    cast(null as double) as demand_mw,
    cast(null as varchar) as source,
    cast(null as varchar) as license
where 1 = 0
