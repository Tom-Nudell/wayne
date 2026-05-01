# @wayne/schema

TS types derived from the Pydantic source of truth in [`platform/data/`](../../platform/data/src/gridagent_data/schema/models.py).

This package is consumed by `web/`, `services/tile-worker/`, and any other TS surface that needs to speak `GridFeature`, `Manifest`, or `LicenseSidecar`. It is the single point where schema drift between the data pipeline and the frontend gets caught.

## How it works

`src/index.ts` is auto-generated. The Pydantic models in `platform/data/src/gridagent_data/schema/models.py` are walked and emitted as TS interfaces and type aliases.

Regenerate from the repo root:

```bash
PYTHONPATH=platform/data/src python -m gridagent_data.schema.generate_ts \
  --out shared/schema/src/index.ts
```

CI fails the build (exit 2) if `src/index.ts` disagrees with what would be generated:

```bash
PYTHONPATH=platform/data/src python -m gridagent_data.schema.generate_ts \
  --out shared/schema/src/index.ts --check
```

The `schema-drift` job in `.github/workflows/ci.yml` runs this on every PR.

## Adding a model

1. Add the Pydantic model to `platform/data/src/gridagent_data/schema/models.py`.
2. Register it in the `_MODELS` (or `_ALIASES` for type aliases) tuple in `generate_ts.py`.
3. Regenerate (command above).
4. Commit the updated `src/index.ts` alongside the Python change.

The generator only understands a narrow subset of Python typing forms (str, int, float, bool, None, `Literal[...]`, `X | None`, `tuple[X, ...]` / `list[X]`, references to other models). Add a case in `_ts_type` if you need something else — don't reach for a general JSON-Schema-to-TS tool unless we have ≥5 unsupported cases.

See [`docs/MONOREPO.md`](../../docs/MONOREPO.md#cross-language-seam) for rationale.
