-- Silver model: EIA plant entity table (geometry + plant name).
--
-- Unlike the SCD plants table (which carries year-by-year regulatory state),
-- the entity table is one row per plant_id_eia with stable identity fields:
-- plant_name_eia, lat/lon, state, county, city. This is the geometry source
-- for the atlas plant layer.

with source as (
    select *
    from read_parquet(
        '{{ env_var("GRIDAGENT_DATA_ROOT", "../../../data_root") }}/bronze/pudl/core_eia__entity_plants/core_eia__entity_plants.parquet'
    )
)

select
    plant_id_eia,
    plant_name_eia,
    state,
    county,
    city,
    latitude,
    longitude,
    timezone,
    'pudl' as source,
    'CC-BY-4.0' as license
from source
