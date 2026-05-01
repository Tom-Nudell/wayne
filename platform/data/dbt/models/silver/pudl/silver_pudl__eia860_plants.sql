-- Silver model: typed, latest EIA-860 plant snapshot.
--
-- The SCD plants parquet carries the slowly-changing fields — BA, NERC
-- region, ISO/RTO code, utility attribution. It does NOT carry plant name
-- or lat/lon (those live in ``core_eia__entity_plants``, an entity table
-- that the bronze loader will pick up once the plant-name / atlas
-- geometry work lands). Today we project only what's actually in the SCD
-- parquet; downstream models LEFT JOIN against this table and tolerate
-- NULL lat/lon.

with source as (
    select *
    from read_parquet(
        '{{ env_var("GRIDAGENT_DATA_ROOT", "../data_root") }}/bronze/pudl/core_eia860__scd_plants/core_eia860__scd_plants.parquet'
    )
),

latest as (
    select
        plant_id_eia,
        balancing_authority_code_eia,
        balancing_authority_name_eia,
        iso_rto_code,
        nerc_region,
        sector_name_eia,
        service_area,
        utility_id_eia,
        report_date,
        row_number() over (
            partition by plant_id_eia
            order by report_date desc
        ) as recency_rank
    from source
)

select
    plant_id_eia,
    balancing_authority_code_eia,
    balancing_authority_name_eia,
    iso_rto_code,
    nerc_region,
    sector_name_eia,
    service_area,
    utility_id_eia,
    report_date,
    'pudl' as source,
    'CC-BY-4.0' as license
from latest
where recency_rank = 1
