"""Dagster ``Definitions`` entrypoint for the gridagent-data project.

The first vertical slice wires only the PUDL bronze loader. Silver and gold
layers are added via dbt (``dagster-dbt`` integration) once the dbt project
under ``dbt/`` has its first models compiled.
"""

from __future__ import annotations

from dagster import Definitions

from gridagent_data.assets import bronze_pudl_assets
from gridagent_data.assets.bronze_pudl import planned_pudl_specs

defs = Definitions(
    assets=[*bronze_pudl_assets, *planned_pudl_specs],
)
