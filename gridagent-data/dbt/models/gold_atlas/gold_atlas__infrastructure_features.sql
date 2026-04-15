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

with plant_features as (
    select
        'plant:eia:' || plant_id_eia as feature_id,
        'plant'::text as kind,
        cast(plant_id_eia as varchar) as display_name,
        json_object(
            'capacity_mw', sum(capacity_mw),
            'fuels', list(distinct fuel_code)
        ) as properties,
        cast(null as varchar) as geometry_wkt,  -- Lat/lon arrives via plants table; placeholder.
        sources,
        licenses
    from {{ ref('gold_network__generators') }}
    group by plant_id_eia, sources, licenses
)

select * from plant_features
