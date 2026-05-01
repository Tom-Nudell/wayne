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
),

osm_raw as (
    select
        src.filename as source_file,
        u.unnest as element
    from read_json_auto(
        [
            '{{ env_var("GRIDAGENT_DATA_ROOT", "../data_root") }}/bronze/osm/us_tx/power.json',
            '{{ env_var("GRIDAGENT_DATA_ROOT", "../data_root") }}/bronze/osm/us_ca/power.json',
            '{{ env_var("GRIDAGENT_DATA_ROOT", "../data_root") }}/bronze/osm/us_ny/power.json'
        ],
        maximum_object_size = 1073741824
    ) src,
    unnest(src.elements) u
),

osm_substations as (
    select
        'substation:osm:' || cast(element.id as varchar) as feature_id,
        'substation' as kind,
        coalesce(element.tags['name'], 'OSM substation ' || cast(element.id as varchar)) as display_name,
        json_object(
            'osm_id', cast(element.id as varchar),
            'power', element.tags['power'],
            'voltage', element.tags['voltage'],
            'operator', element.tags['operator'],
            'source_file', source_file
        ) as properties,
        case
            when element.type = 'node'
                then 'POINT(' || cast(element.lon as varchar) || ' ' || cast(element.lat as varchar) || ')'
            when element.type = 'way' and array_length(element.geometry) > 0
                then 'POINT('
                    || cast(element.geometry[1].lon as varchar) || ' '
                    || cast(element.geometry[1].lat as varchar) || ')'
            else null
        end as geometry_wkt,
        ['osm'] as sources,
        ['ODbL-1.0'] as licenses
    from osm_raw
    where coalesce(element.tags['power'], '') = 'substation'
),

osm_plants as (
    select
        'plant:osm:' || cast(element.id as varchar) as feature_id,
        'plant' as kind,
        coalesce(element.tags['name'], 'OSM plant ' || cast(element.id as varchar)) as display_name,
        json_object(
            'osm_id', cast(element.id as varchar),
            'power', element.tags['power'],
            'plant_source', element.tags['plant:source'],
            'generator_source', element.tags['generator:source'],
            'capacity', element.tags['plant:output:electricity'],
            'source_file', source_file
        ) as properties,
        case
            when element.type = 'node'
                then 'POINT(' || cast(element.lon as varchar) || ' ' || cast(element.lat as varchar) || ')'
            when element.type = 'way' and array_length(element.geometry) > 0
                then 'POINT('
                    || cast(element.geometry[1].lon as varchar) || ' '
                    || cast(element.geometry[1].lat as varchar) || ')'
            else null
        end as geometry_wkt,
        ['osm'] as sources,
        ['ODbL-1.0'] as licenses
    from osm_raw
    where coalesce(element.tags['power'], '') in ('plant', 'generator')
),

osm_linestrings as (
    select
        element.id as osm_id,
        source_file,
        element.tags as tags,
        string_agg(
            cast(g.unnest.lon as varchar) || ' ' || cast(g.unnest.lat as varchar),
            ', ' order by g.ordinality
        ) as coord_list
    from osm_raw,
    unnest(element.geometry) with ordinality as g(unnest, ordinality)
    where element.type = 'way'
    group by 1, 2, 3
),

osm_transmission_lines as (
    select
        'transmission_line:osm:' || cast(osm_id as varchar) as feature_id,
        'transmission_line' as kind,
        coalesce(tags['name'], 'OSM line ' || cast(osm_id as varchar)) as display_name,
        json_object(
            'osm_id', cast(osm_id as varchar),
            'power', tags['power'],
            'voltage', tags['voltage'],
            'circuits', tags['circuits'],
            'operator', tags['operator'],
            'source_file', source_file
        ) as properties,
        'LINESTRING(' || coord_list || ')' as geometry_wkt,
        ['osm'] as sources,
        ['ODbL-1.0'] as licenses
    from osm_linestrings
    where coalesce(tags['power'], '') in ('line', 'minor_line', 'cable')
),

osm_gas_pipelines as (
    select
        'gas_pipeline:osm:' || cast(osm_id as varchar) as feature_id,
        'gas_pipeline' as kind,
        coalesce(tags['name'], 'OSM gas pipeline ' || cast(osm_id as varchar)) as display_name,
        json_object(
            'osm_id', cast(osm_id as varchar),
            'man_made', tags['man_made'],
            'substance', tags['substance'],
            'operator', tags['operator'],
            'diameter', tags['diameter'],
            'source_file', source_file
        ) as properties,
        'LINESTRING(' || coord_list || ')' as geometry_wkt,
        ['osm'] as sources,
        ['ODbL-1.0'] as licenses
    from osm_linestrings
    where coalesce(tags['man_made'], '') = 'pipeline'
      and lower(coalesce(tags['substance'], '')) = 'gas'
),

queue_projects as (
    select
        'queue_project:' || q.project_id as feature_id,
        'queue_project' as kind,
        coalesce(q.point_of_interconnection, q.project_id) as display_name,
        json_object(
            'project_id', q.project_id,
            'iso_region', q.iso_region,
            'queue_status', q.queue_status,
            'fuel_type', q.fuel_type,
            'capacity_mw', q.capacity_mw,
            'queue_date', q.queue_date,
            'proposed_completion_date', q.proposed_completion_date
        ) as properties,
        case
            when q.poi_longitude is not null and q.poi_latitude is not null
                then 'POINT(' || cast(q.poi_longitude as varchar)
                    || ' ' || cast(q.poi_latitude as varchar) || ')'
            else null
        end as geometry_wkt,
        [coalesce(q.source, 'queue_feed')] as sources,
        [coalesce(q.license, 'unknown')] as licenses
    from {{ ref('gold_market__queue_snapshot') }} q
)

select * from pudl_plants
union all by name
select * from rts_substations
union all by name
select * from rts_lines
union all by name
select * from osm_substations
union all by name
select * from osm_plants
union all by name
select * from osm_transmission_lines
union all by name
select * from osm_gas_pipelines
union all by name
select * from queue_projects
