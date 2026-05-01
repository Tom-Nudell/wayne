-- Gold market mart: interconnection queue snapshot.
--
-- Backed by the silver queue feed model, populated from a daily remote CSV
-- source (configured via GRIDAGENT_QUEUE_CSV_URL in the bronze ingest step).

select
    project_id,
    snapshot_date,
    iso_region,
    queue_status,
    fuel_type,
    capacity_mw,
    queue_date,
    proposed_completion_date,
    point_of_interconnection,
    poi_latitude,
    poi_longitude,
    source,
    license
from {{ ref('silver_queue_feed__projects') }}
