-- Silver model: typed RTS-GMLC generator list.
--
-- Fuel strings are normalised to lower_snake so they match the enum used by
-- the pandapower backend's ``_FUEL_COST_USD_PER_MWH`` lookup.

with source as (
    select *
    from read_csv_auto(
        '{{ env_var("GRIDAGENT_DATA_ROOT", "../data_root") }}/bronze/rts_gmlc/gen.csv',
        header = true
    )
)

select
    cast("GEN UID" as varchar) as generator_id,
    cast("Bus ID" as varchar) as bus_id,
    cast("PMax MW" as double) as p_max_mw,
    cast("PMin MW" as double) as p_min_mw,
    cast("QMax MVAR" as double) as q_max_mvar,
    cast("QMin MVAR" as double) as q_min_mvar,
    lower(replace(cast("Fuel" as varchar), ' ', '_')) as fuel,
    cast("Unit Type" as varchar) as unit_type,
    cast("Category" as varchar) as category,
    'rts_gmlc' as source,
    'BSD-3-Clause' as license
from source
