-- Silver model: EIA-923 monthly net generation by generator.
--
-- One row per (plant, generator, month). Consumed by gold_market models
-- that aggregate actual monthly energy to compare against simulated PCM
-- output, and by gold_network to derive realized capacity factors per
-- fuel type (useful for imputing p_min_mw when source data is missing).

with source as (
    select *
    from read_parquet(
        '{{ env_var("GRIDAGENT_DATA_ROOT", "../data_root") }}/bronze/pudl/core_eia923__monthly_generation/core_eia923__monthly_generation.parquet'
    )
)

select
    plant_id_eia,
    generator_id,
    report_date,
    net_generation_mwh,
    'pudl' as source,
    'CC-BY-4.0' as license
from source
where net_generation_mwh is not null
