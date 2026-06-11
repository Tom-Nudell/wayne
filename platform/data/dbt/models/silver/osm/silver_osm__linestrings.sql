-- Silver: OSM way linestrings with concatenated coord lists.
--
-- One row per `way` whose tags carry power=line/cable or
-- man_made=pipeline+substance=gas. Coordinates are pre-joined into a
-- WKT-ready string so gold transforms are O(rows) instead of O(rows ×
-- vertices) per CTE reference.

{{ config(materialized='table') }}

select
    element.id as osm_id,
    source_file,
    element.tags as tags,
    string_agg(
        cast(g.unnest.lon as varchar) || ' ' || cast(g.unnest.lat as varchar),
        ', ' order by g.ordinality
    ) as coord_list
from {{ ref('silver_osm__elements') }},
    unnest(element.geometry) with ordinality as g(unnest, ordinality)
where element.type = 'way'
  and (
       coalesce(element.tags['power'], '') in ('line', 'cable')
    or (coalesce(element.tags['man_made'], '') = 'pipeline'
         and lower(coalesce(element.tags['substance'], '')) = 'gas')
  )
group by 1, 2, 3
