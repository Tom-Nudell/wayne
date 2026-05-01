"""Dagster bronze assets for PUDL parquet tables.

Each table in :data:`gridagent_data.sources.pudl.TABLES` becomes its own asset
so that Dagster can independently materialize, monitor freshness, and surface
metadata (etag, byte size, source URL) per table.
"""

from __future__ import annotations

from dagster import AssetExecutionContext, AssetSpec, MetadataValue, asset

from gridagent_data.sources.pudl import TABLES, fetch_table


def _make_asset(table):
    @asset(
        name=f"bronze_pudl__{table.name}",
        group_name="bronze_pudl",
        description=table.description,
        compute_kind="http",
    )
    def _bronze_asset(context: AssetExecutionContext) -> None:
        manifest = fetch_table(table)
        context.add_output_metadata(
            {
                "source_url": MetadataValue.url(manifest["url"]),
                "bytes": MetadataValue.int(manifest["bytes"]),
                "etag": MetadataValue.text(manifest["etag"]),
                "retrieved_at": MetadataValue.text(manifest["retrieved_at"]),
                "license": MetadataValue.text(manifest["source"]["license"]),
                "bronze_path": MetadataValue.path(manifest["path"]),
            }
        )

    return _bronze_asset


bronze_pudl_assets: list = [_make_asset(t) for t in TABLES]


# AssetSpec stubs for tables we plan to add but haven't wired loaders for yet.
# Surfacing them in the Dagster lineage UI keeps the roadmap visible.
planned_pudl_specs = [
    AssetSpec(
        key=f"bronze_pudl__{name}",
        group_name="bronze_pudl_planned",
        description=desc,
        metadata={"status": "planned"},
    )
    for name, desc in (
        ("core_eia860__scd_plants", "EIA-860 plants (slowly changing)"),
        ("core_eia923__monthly_generation", "EIA-923 monthly generation by generator"),
        ("core_eia930__hourly_operations", "EIA-930 hourly demand/generation by BA"),
        ("core_epacems__hourly_emissions", "EPA CEMS hourly emissions"),
        ("core_ferc714__hourly_planning_area_demand", "FERC-714 hourly demand"),
    )
]
