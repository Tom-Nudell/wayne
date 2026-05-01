-- Gold network mart: canonical branch dimension.

with rts_branches as (
    select
        'RTS-' || branch_id as branch_id,
        branch_id as native_branch_id,
        'RTS-' || from_bus_id as from_bus_id,
        'RTS-' || to_bus_id as to_bus_id,
        r_pu,
        x_pu,
        b_pu,
        rating_a_mva,
        rating_b_mva,
        rating_c_mva,
        array_value(source) as sources,
        array_value(license) as licenses
    from {{ ref('silver_rts_gmlc__branches') }}
)

select * from rts_branches
