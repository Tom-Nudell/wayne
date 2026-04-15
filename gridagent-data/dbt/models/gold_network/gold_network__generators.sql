-- Gold network mart: canonical generator dimension.
--
-- Sienna-bound. Each row is a generator unit annotated with the source layer
-- that contributed it. For now we have a single source (PUDL EIA-860); more
-- sources (PyPSA-USA aggregated buses, OSM-derived units) will be unioned in
-- here with deterministic conflict-resolution rules documented per source.
-- Global units are deferred until a fully-open global source is identified.

with pudl_units as (
    select
        plant_id_eia,
        generator_id,
        capacity_mw,
        summer_capacity_mw,
        winter_capacity_mw,
        energy_source_code_1 as fuel_code,
        prime_mover_code,
        technology_description,
        operating_date,
        retirement_date,
        operational_status_code,
        source,
        license
    from {{ ref('silver_pudl__eia860_generators') }}
    where operational_status_code in ('OP', 'SB', 'OS', 'TS', 'L', 'T', 'P')
)

select
    'EIA-' || plant_id_eia || '-' || generator_id as generator_id,
    plant_id_eia,
    generator_id as eia_generator_id,
    capacity_mw,
    summer_capacity_mw,
    winter_capacity_mw,
    fuel_code,
    prime_mover_code,
    technology_description,
    operating_date,
    retirement_date,
    operational_status_code,
    array_value(source) as sources,
    array_value(license) as licenses
from pudl_units
