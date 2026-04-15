-- Gold atlas mart: visualization-grade feature catalog.
--
-- One row per physical thing on the map, with a ``kind`` discriminator. Schema
-- is open-set so new feature types (data_center, gas_pipeline, …) just add new
-- ``kind`` values rather than new tables. Geometry is WKT here; the parquet
-- exporter promotes it to GeoArrow for tippecanoe.
--
-- Lessons from OpenGridWorks captured in this schema:
--   * Per-row ``sources`` and ``licenses`` so the atlas popover can attribute
--     correctly without joining back to the mart at request time.
--   * Open-set ``kind`` so we can add gas/fiber/datacenters later without
--     schema migrations.

with pudl_plants as (
    -- Plants arrive as aggregated generator rollups. Lat/lon is NULL until
    -- the ``core_eia__entity_plants`` ingest lands; the atlas tolerates
    -- missing geometry and simply omits those points from the tile build.
    select
        'plant:eia:' || g.plant_id_eia as feature_id,
        'plant' as kind,
        cast(g.plant_id_eia as varchar) as display_name,
        json_object(
            'plant_id_eia', g.plant_id_eia,
            'capacity_mw', sum(g.capacity_mw),
            'fuels', list(distinct g.fuel_code),
            'balancing_authority', any_value(p.balancing_authority_code_eia),
            'iso_rto_code', any_value(p.iso_rto_code),
            'nerc_region', any_value(p.nerc_region)
        ) as properties,
        cast(null as varchar) as geometry_wkt,
        any_value(g.sources) as sources,
        any_value(g.licenses) as licenses
    from {{ ref('gold_network__generators') }} g
    left join {{ ref('silver_pudl__eia860_plants') }} p
        on g.plant_id_eia = p.plant_id_eia
    group by g.plant_id_eia
),

rts_substations as (
    select
        'substation:rts:' || native_bus_id as feature_id,
        'substation' as kind,
        name as display_name,
        json_object(
            'bus_id', bus_id,
            'base_kv', base_kv,
            'area', area,
            'zone', zone
        ) as properties,
        case
            when longitude is not null and latitude is not null
                then 'POINT(' || cast(longitude as varchar)
                    || ' ' || cast(latitude as varchar) || ')'
            else null
        end as geometry_wkt,
        sources,
        licenses
    from {{ ref('gold_network__buses') }}
    where 'rts_gmlc' = any(sources)
),

rts_lines as (
    select
        'transmission_line:rts:' || br.native_branch_id as feature_id,
        'transmission_line' as kind,
        br.native_branch_id as display_name,
        json_object(
            'branch_id', br.branch_id,
            'from_bus_id', br.from_bus_id,
            'to_bus_id', br.to_bus_id,
            'rating_a_mva', br.rating_a_mva,
            'base_kv', coalesce(bf.base_kv, bt.base_kv)
        ) as properties,
        case
            when bf.longitude is not null and bf.latitude is not null
                 and bt.longitude is not null and bt.latitude is not null
                then 'LINESTRING('
                    || cast(bf.longitude as varchar) || ' '
                    || cast(bf.latitude as varchar) || ', '
                    || cast(bt.longitude as varchar) || ' '
                    || cast(bt.latitude as varchar) || ')'
            else null
        end as geometry_wkt,
        br.sources,
        br.licenses
    from {{ ref('gold_network__branches') }} br
    left join {{ ref('gold_network__buses') }} bf on br.from_bus_id = bf.bus_id
    left join {{ ref('gold_network__buses') }} bt on br.to_bus_id = bt.bus_id
)

select * from pudl_plants
union all by name
select * from rts_substations
union all by name
select * from rts_lines
