-- Gold market mart: interconnection queue snapshot.
--
-- One row per (project_id, snapshot_date). Populated by the LBNL
-- Queued Up bronze loader once it lands. Status, fuel, capacity, and POI
-- attributes let the agent answer "what's queued near this substation?"
-- and "what is the queue-through rate in ERCOT for solar?" without
-- additional joins.

select
    cast(null as varchar) as project_id,
    cast(null as date) as snapshot_date,
    cast(null as varchar) as iso_region,
    cast(null as varchar) as queue_status,
    cast(null as varchar) as fuel_type,
    cast(null as double) as capacity_mw,
    cast(null as date) as queue_date,
    cast(null as date) as proposed_completion_date,
    cast(null as varchar) as point_of_interconnection,
    cast(null as double) as poi_latitude,
    cast(null as double) as poi_longitude,
    cast(null as varchar) as source,
    cast(null as varchar) as license
where 1 = 0
