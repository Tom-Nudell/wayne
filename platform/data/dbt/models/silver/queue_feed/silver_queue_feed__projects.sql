with source as (
    select *
    from read_csv_auto(
        '{{ env_var("GRIDAGENT_DATA_ROOT", "../data_root") }}/bronze/queue_feed/latest.csv',
        header = true
    )
)

select
    cast(project_id as varchar) as project_id,
    cast(snapshot_date as date) as snapshot_date,
    cast(iso_region as varchar) as iso_region,
    cast(queue_status as varchar) as queue_status,
    cast(fuel_type as varchar) as fuel_type,
    cast(capacity_mw as double) as capacity_mw,
    cast(queue_date as date) as queue_date,
    cast(proposed_completion_date as date) as proposed_completion_date,
    cast(point_of_interconnection as varchar) as point_of_interconnection,
    cast(poi_latitude as double) as poi_latitude,
    cast(poi_longitude as double) as poi_longitude,
    cast(source as varchar) as source,
    cast(license as varchar) as license
from source
