-- Silver model: typed, normalised EIA-860 generators.
--
-- Reads the bronze parquet that ``bronze_pudl__core_eia860__scd_generators``
-- materialised. We project only the columns the downstream gold marts care
-- about, normalise units (capacity in MW), and stamp provenance.
--
-- Conflicts resolved here:
--   * Multiple report years per (plant, generator) → keep the latest report_date.
--   * Whitespace + casing in fuel/technology fields → upper-snake-case enums.

with source as (
    select *
    from read_parquet(
        '{{ env_var("GRIDAGENT_DATA_ROOT", "../data_root") }}/bronze/pudl/core_eia860__scd_generators/core_eia860__scd_generators.parquet'
    )
),

ranked as (
    select
        plant_id_eia,
        generator_id,
        report_date,
        operational_status_code,
        capacity_mw,
        summer_capacity_mw,
        winter_capacity_mw,
        energy_source_code_1,
        prime_mover_code,
        technology_description,
        current_planned_generator_operating_date as operating_date,
        generator_retirement_date as retirement_date,
        row_number() over (
            partition by plant_id_eia, generator_id
            order by report_date desc
        ) as recency_rank
    from source
)

select
    plant_id_eia,
    generator_id,
    report_date,
    upper(coalesce(operational_status_code, '')) as operational_status_code,
    capacity_mw,
    summer_capacity_mw,
    winter_capacity_mw,
    upper(coalesce(energy_source_code_1, '')) as energy_source_code_1,
    upper(coalesce(prime_mover_code, '')) as prime_mover_code,
    technology_description,
    operating_date,
    retirement_date,
    'pudl' as source,
    'CC-BY-4.0' as license
from ranked
where recency_rank = 1
