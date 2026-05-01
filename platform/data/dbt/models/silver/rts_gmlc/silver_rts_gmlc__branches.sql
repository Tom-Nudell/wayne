-- Silver model: typed RTS-GMLC branch list.

with source as (
    select *
    from read_csv_auto(
        '{{ env_var("GRIDAGENT_DATA_ROOT", "../data_root") }}/bronze/rts_gmlc/branch.csv',
        header = true
    )
)

select
    cast("UID" as varchar) as branch_id,
    cast("From Bus" as varchar) as from_bus_id,
    cast("To Bus" as varchar) as to_bus_id,
    cast("R" as double) as r_pu,
    cast("X" as double) as x_pu,
    cast("B" as double) as b_pu,
    cast("Cont Rating" as double) as rating_a_mva,
    cast("LTE Rating" as double) as rating_b_mva,
    cast("STE Rating" as double) as rating_c_mva,
    'rts_gmlc' as source,
    'BSD-3-Clause' as license
from source
