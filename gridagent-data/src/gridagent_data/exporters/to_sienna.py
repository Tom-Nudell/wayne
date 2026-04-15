"""Export gold marts to a MATPOWER ``.m`` file consumable by ``PowerSystems.jl``.

Stub. Real implementation lands once ``gold_network__buses`` and
``gold_network__branches`` have rows. The function signature is fixed now so
``gridagent-julia`` can target it.
"""

from __future__ import annotations

from pathlib import Path


def export(snapshot_dir: Path, out_dir: Path) -> Path:
    """Write a MATPOWER case file plus EIA sidecar JSON.

    Returns the path to the ``.m`` file. The sidecar JSON, named
    ``{stem}_eia.json``, maps MATPOWER bus/branch/gen indices back to
    canonical gold-network IDs so result rows can rejoin the warehouse.
    """
    raise NotImplementedError("Wired up once gold_network__buses lands.")
