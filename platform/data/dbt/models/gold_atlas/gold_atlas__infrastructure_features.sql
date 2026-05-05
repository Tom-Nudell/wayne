-- Gold atlas mart: visualization-grade feature catalog.
--
-- One row per physical thing on the map, with a ``kind`` discriminator. Schema
-- is open-set so new feature types (data_center, gas_pipeline, …) just add new
-- ``kind`` values rather than new tables. Geometry is WKT here; the parquet
-- exporter promotes it to GeoArrow for tippecanoe.
--
-- Top-level fields (voltage_kv, capacity_mw, fuel) are normalized across
-- sources so the MapLibre paint specs find them via ["get", "voltage_kv"]
-- without having to dig into a JSON properties blob. Source-specific
-- attributes still live in ``properties`` (JSON) for popovers.
--
-- Filtering rationale (brief §7 — data quality is the moat):
--   * OSM `power=generator` is excluded — those are individual turbines /
--     rooftop panels and would drown the layer in noise. Keep `power=plant`.
--   * OSM transmission below 60 kV is dropped — distribution clutter.
--   * Queue projects must be in an active status AND have at least one of
--     fuel_type or capacity_mw — sparse "Withdrawn / no metadata" rows do
--     not earn map real estate.
--   * PUDL plants without geometry are emitted with NULL geometry_wkt and
--     are dropped by the tile exporter; the silver model needs the
--     ``core_eia__entity_plants`` lat/lon ingest before they show up.

{% set fuel_normalize %}
case lower(coalesce({fuel_in}, ''))
    when 'solar' then 'solar'
    when 'sun' then 'solar'
    when 'pv' then 'solar'
    when 'photovoltaic' then 'solar'
    when 'wind' then 'wind'
    when 'wnd' then 'wind'
    when 'natural_gas' then 'natural_gas'
    when 'gas' then 'natural_gas'
    when 'ng' then 'natural_gas'
    when 'coal' then 'coal'
    when 'bit' then 'coal'
    when 'sub' then 'coal'
    when 'lig' then 'coal'
    when 'ant' then 'coal'
    when 'nuclear' then 'nuclear'
    when 'nuc' then 'nuclear'
    when 'hydro' then 'hydro'
    when 'wat' then 'hydro'
    when 'oil' then 'oil'
    when 'dfo' then 'oil'
    when 'rfo' then 'oil'
    when 'ker' then 'oil'
    when 'biomass' then 'biomass'
    when 'wood' then 'biomass'
    when 'wds' then 'biomass'
    when 'biogas' then 'biomass'
    when 'lfg' then 'biomass'
    when 'geothermal' then 'geothermal'
    when 'geo' then 'geothermal'
    when 'battery' then 'battery'
    when 'storage' then 'battery'
    when '' then null
    else 'other'
end
{% endset %}

-- RTS-GMLC (the synthetic 73-bus research test system) is intentionally
-- excluded from this mart. The agent platform (platform/orchestrator) still
-- uses it for studies, but the customer-facing map renders only real US
-- infrastructure. To re-enable for an internal viewer, add a feature flag
-- on the ``gold_network__buses`` source filter.
--
-- PUDL plants are aggregated generator rollups grouped by plant_id_eia.
-- Today they have NULL geometry (the silver model does not yet pull
-- ``core_eia__entity_plants`` lat/lon). The tile exporter drops features
-- with NULL geometry, so PUDL plants are invisible on the map until that
-- ingest lands. They stay in the mart so the schema is correct and so
-- DuckDB-WASM queries against the bundle return them.
with pudl_plants as (
    select
        'plant:eia:' || g.plant_id_eia as feature_id,
        'plant' as kind,
        coalesce(any_value(e.plant_name_eia), cast(g.plant_id_eia as varchar)) as display_name,
        json_object(
            'plant_id_eia', g.plant_id_eia,
            'plant_name', any_value(e.plant_name_eia),
            'state', any_value(e.state),
            'county', any_value(e.county),
            'capacity_mw', sum(g.capacity_mw),
            'fuels', list(distinct g.fuel_code),
            'balancing_authority', any_value(p.balancing_authority_code_eia),
            'iso_rto_code', any_value(p.iso_rto_code),
            'nerc_region', any_value(p.nerc_region),
            'voltage_kv', null,
            'fuel', {{ fuel_normalize | replace('{fuel_in}', 'mode(g.fuel_code)') }}
        ) as properties,
        cast(null as double) as voltage_kv,
        sum(g.capacity_mw) as capacity_mw,
        {{ fuel_normalize | replace('{fuel_in}', 'mode(g.fuel_code)') }} as fuel,
        case
            when any_value(e.latitude) is not null and any_value(e.longitude) is not null
                then 'POINT(' || cast(any_value(e.longitude) as varchar)
                    || ' ' || cast(any_value(e.latitude) as varchar) || ')'
            else null
        end as geometry_wkt,
        any_value(g.sources) as sources,
        any_value(g.licenses) as licenses
    from {{ ref('gold_network__generators') }} g
    left join {{ ref('silver_pudl__eia860_plants') }} p
        on g.plant_id_eia = p.plant_id_eia
    left join {{ ref('silver_pudl__eia_entity_plants') }} e
        on g.plant_id_eia = e.plant_id_eia
    where g.plant_id_eia is not null  -- excludes RTS-GMLC synthetic generators
    group by g.plant_id_eia
),

-- OSM elements come from a materialized silver table so this gold model
-- doesn't re-parse the ~3 GB of bronze JSON for each downstream CTE. See
-- silver_osm__elements / silver_osm__linestrings.
osm_raw as (
    select source_file, element from {{ ref('silver_osm__elements') }}
),

-- Volt-string parser: OSM `voltage` is volts as string, sometimes
-- semicolon-separated (e.g. "138000;345000"). Take the first numeric
-- chunk; treat values > 1000 as volts (divide by 1000), values <= 1000
-- as already-kV (rare but possible).
osm_substations as (
    select
        'substation:osm:' || cast(element.id as varchar) as feature_id,
        'substation' as kind,
        coalesce(element.tags['name'], 'OSM substation ' || cast(element.id as varchar)) as display_name,
        case
            when try_cast(split_part(element.tags['voltage'], ';', 1) as integer) is null then null
            when try_cast(split_part(element.tags['voltage'], ';', 1) as integer) > 1000
                then try_cast(split_part(element.tags['voltage'], ';', 1) as double) / 1000.0
            else try_cast(split_part(element.tags['voltage'], ';', 1) as double)
        end as voltage_kv_calc,
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

osm_substations_final as (
    select
        feature_id,
        kind,
        display_name,
        json_merge_patch(properties, json_object('voltage_kv', voltage_kv_calc)) as properties,
        voltage_kv_calc as voltage_kv,
        cast(null as double) as capacity_mw,
        cast(null as varchar) as fuel,
        geometry_wkt,
        sources,
        licenses
    from osm_substations
),

-- Plants from OSM: `power=plant` only (utility-scale farms / facilities).
-- Excludes `power=generator` (individual turbines, rooftop panels) which
-- would drown the layer in 700K+ noise rows. Capacity parsed best-effort
-- from `plant:output:electricity` (e.g. "100 MW", "1.5 MW").
osm_plants as (
    select
        'plant:osm:' || cast(element.id as varchar) as feature_id,
        'plant' as kind,
        coalesce(element.tags['name'], 'OSM plant ' || cast(element.id as varchar)) as display_name,
        -- Capacity parser: leading float, optional whitespace, optional MW unit.
        case
            when element.tags['plant:output:electricity'] is null then null
            when regexp_extract(
                element.tags['plant:output:electricity'],
                '^([0-9]+(?:\.[0-9]+)?)\s*(?:MW|mw)?', 1
            ) = '' then null
            else try_cast(
                regexp_extract(
                    element.tags['plant:output:electricity'],
                    '^([0-9]+(?:\.[0-9]+)?)\s*(?:MW|mw)?', 1
                ) as double
            )
        end as capacity_mw_calc,
        coalesce(element.tags['plant:source'], element.tags['generator:source']) as fuel_in,
        json_object(
            'osm_id', cast(element.id as varchar),
            'power', element.tags['power'],
            'plant_source', element.tags['plant:source'],
            'capacity_raw', element.tags['plant:output:electricity'],
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
    where coalesce(element.tags['power'], '') = 'plant'
),

osm_plants_final as (
    select
        feature_id,
        kind,
        display_name,
        json_merge_patch(
            properties,
            json_object('capacity_mw', capacity_mw_calc, 'fuel', {{ fuel_normalize | replace('{fuel_in}', 'fuel_in') }})
        ) as properties,
        cast(null as double) as voltage_kv,
        capacity_mw_calc as capacity_mw,
        {{ fuel_normalize | replace('{fuel_in}', 'fuel_in') }} as fuel,
        geometry_wkt,
        sources,
        licenses
    from osm_plants
),

osm_linestrings as (
    select osm_id, source_file, tags, coord_list
    from {{ ref('silver_osm__linestrings') }}
),

-- Transmission: drop OSM `power=line` below 60 kV (distribution noise).
-- Treat unparseable voltage as null and exclude from this layer.
osm_transmission_lines as (
    select
        'transmission_line:osm:' || cast(osm_id as varchar) as feature_id,
        'transmission_line' as kind,
        coalesce(tags['name'], 'OSM line ' || cast(osm_id as varchar)) as display_name,
        case
            when try_cast(split_part(tags['voltage'], ';', 1) as integer) is null then null
            when try_cast(split_part(tags['voltage'], ';', 1) as integer) > 1000
                then try_cast(split_part(tags['voltage'], ';', 1) as double) / 1000.0
            else try_cast(split_part(tags['voltage'], ';', 1) as double)
        end as voltage_kv_calc,
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
    where coalesce(tags['power'], '') in ('line', 'cable')
),

osm_transmission_lines_final as (
    select
        feature_id,
        kind,
        display_name,
        json_merge_patch(properties, json_object('voltage_kv', voltage_kv_calc)) as properties,
        voltage_kv_calc as voltage_kv,
        cast(null as double) as capacity_mw,
        cast(null as varchar) as fuel,
        geometry_wkt,
        sources,
        licenses
    from osm_transmission_lines
    where voltage_kv_calc is not null and voltage_kv_calc >= 60
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
        cast(null as double) as voltage_kv,
        cast(null as double) as capacity_mw,
        cast(null as varchar) as fuel,
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
            'proposed_completion_date', q.proposed_completion_date,
            'fuel', {{ fuel_normalize | replace('{fuel_in}', 'q.fuel_type') }}
        ) as properties,
        cast(null as double) as voltage_kv,
        q.capacity_mw,
        {{ fuel_normalize | replace('{fuel_in}', 'q.fuel_type') }} as fuel,
        case
            when q.poi_longitude is not null and q.poi_latitude is not null
                then 'POINT(' || cast(q.poi_longitude as varchar)
                    || ' ' || cast(q.poi_latitude as varchar) || ')'
            else null
        end as geometry_wkt,
        [coalesce(q.source, 'queue_feed')] as sources,
        [coalesce(q.license, 'unknown')] as licenses
    from {{ ref('gold_market__queue_snapshot') }} q
    -- Drop withdrawn/completed historical entries and rows with zero metadata.
    where lower(coalesce(q.queue_status, '')) in (
        'active', 'pending', 'in construction', 'construction',
        'planning', 'studied', 'studies underway', 'feasibility',
        'system impact study', 'facilities study', 'i.a. signed',
        'ia signed', 'interconnection agreement signed', 'operational'
    )
      and (q.fuel_type is not null or q.capacity_mw is not null)
)

select * from pudl_plants
union all by name
select * from osm_substations_final
union all by name
select * from osm_plants_final
union all by name
select * from osm_transmission_lines_final
union all by name
select * from osm_gas_pipelines
union all by name
select * from queue_projects
