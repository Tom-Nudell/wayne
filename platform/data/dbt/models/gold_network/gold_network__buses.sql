-- Gold network mart: canonical bus dimension.
--
-- Sienna-bound. RTS-GMLC is the only source today; PyPSA-USA and HIFLD
-- unification lands once those bronze loaders exist. We namespace the
-- canonical ID with the source family prefix so cross-source joins stay
-- unambiguous when multi-source merging begins.

with rts_buses as (
    select
        'RTS-' || bus_id as bus_id,
        bus_id as native_bus_id,
        name,
        base_kv,
        area,
        zone,
        latitude,
        longitude,
        bus_type,
        array_value(source) as sources,
        array_value(license) as licenses
    from {{ ref('silver_rts_gmlc__buses') }}
)

select * from rts_buses
