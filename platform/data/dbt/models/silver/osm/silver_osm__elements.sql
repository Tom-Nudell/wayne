-- Silver: flattened OSM elements across all per-state bronze extracts.
--
-- Reads from per-state parquet files written by the OSM bronze
-- post-processor (one row per OSM element). Reading parquet instead
-- of the original ~3 GB of JSON keeps memory bounded and lets the
-- gold layer reference this table four times without OOMing.
--
-- The parquet files are produced by `gridagent_data.sources.osm.bronze`
-- after each Overpass fetch (or via the standalone preprocessor); the
-- bronze JSON remains on disk as the immutable original.

{{ config(materialized='table') }}

select
    region,
    source_file,
    element
from read_parquet(
    '{{ env_var("GRIDAGENT_DATA_ROOT", "../../../data_root") }}/bronze/osm/*/elements.parquet'
)
