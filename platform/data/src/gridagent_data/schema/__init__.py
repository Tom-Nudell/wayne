"""Pydantic schema — the source of truth for cross-language contracts.

The TS types in ``shared/schema/`` are generated from these models. CI
fails the build if they drift. See :mod:`gridagent_data.schema.models`
for what's defined and :mod:`gridagent_data.schema.generate_ts` for the
emitter.
"""

from gridagent_data.schema import models  # re-exported for convenience

__all__ = ["models"]
