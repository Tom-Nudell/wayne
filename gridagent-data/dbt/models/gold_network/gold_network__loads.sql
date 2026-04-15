-- Gold network mart: canonical load dimension.

with rts_loads as (
    select
        'RTS-' || load_id as load_id,
        load_id as native_load_id,
        'RTS-' || bus_id as bus_id,
        p_mw,
        q_mvar,
        array_value(source) as sources,
        array_value(license) as licenses
    from {{ ref('silver_rts_gmlc__loads') }}
)

select * from rts_loads
