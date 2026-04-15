-- Silver model: typed RTS-GMLC bus list.
--
-- RTS-GMLC stores load PQ values on the bus row itself; we split the load
-- out into ``silver_rts_gmlc__loads`` and keep this model purely topological.

with source as (
    select *
    from read_csv_auto(
        '{{ env_var("GRIDAGENT_DATA_ROOT", "../data_root") }}/bronze/rts_gmlc/bus.csv',
        header = true
    )
)

select
    cast("Bus ID" as varchar) as bus_id,
    cast("Bus Name" as varchar) as name,
    cast("BaseKV" as double) as base_kv,
    cast("Area" as varchar) as area,
    cast("Zone" as varchar) as zone,
    cast("lat" as double) as latitude,
    cast("lng" as double) as longitude,
    upper(coalesce("Bus Type", 'PQ')) as bus_type,
    'rts_gmlc' as source,
    'BSD-3-Clause' as license
from source
