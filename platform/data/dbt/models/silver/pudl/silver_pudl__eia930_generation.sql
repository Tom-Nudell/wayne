-- Silver model: EIA-930 hourly net generation by BA + energy source.
--
-- One row per (balancing_authority, hour, energy_source). The parquet
-- carries three generation series; we prefer PUDL's adjusted series and
-- fall back to reported, then imputed, so every row that has any value
-- yields one. Rows where all three are NULL are dropped.

with source as (
    select *
    from read_parquet(
        '{{ env_var("GRIDAGENT_DATA_ROOT", "../data_root") }}/bronze/pudl/core_eia930__hourly_net_generation_by_energy_source/core_eia930__hourly_net_generation_by_energy_source.parquet'
    )
)

select
    balancing_authority_code_eia as balancing_authority,
    datetime_utc as interval_start_utc,
    generation_energy_source as fuel_type,
    coalesce(
        net_generation_adjusted_mwh,
        net_generation_reported_mwh,
        net_generation_imputed_eia_mwh
    ) as generation_mwh,
    'pudl' as source,
    'CC-BY-4.0' as license
from source
where coalesce(
    net_generation_adjusted_mwh,
    net_generation_reported_mwh,
    net_generation_imputed_eia_mwh
) is not null
