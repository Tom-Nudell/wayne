-- Silver model: loads extracted from RTS-GMLC bus PQ values.
--
-- RTS-GMLC carries load inline on the bus row. We split it out so the gold
-- network mart can have a real load dimension. Buses with zero injection
-- are dropped so the mart reflects where demand actually lives.

with source as (
    select *
    from read_csv_auto(
        '{{ env_var("GRIDAGENT_DATA_ROOT", "../data_root") }}/bronze/rts_gmlc/bus.csv',
        header = true
    )
)

select
    'L_' || cast("Bus ID" as varchar) as load_id,
    cast("Bus ID" as varchar) as bus_id,
    cast("MW Load" as double) as p_mw,
    cast("MVAR Load" as double) as q_mvar,
    'rts_gmlc' as source,
    'BSD-3-Clause' as license
from source
where abs(coalesce(cast("MW Load" as double), 0))
    + abs(coalesce(cast("MVAR Load" as double), 0)) > 0
