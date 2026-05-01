# @wayne/schema

TS types derived from the Pydantic source of truth in `platform/data/`.

This package is consumed by `web/`, `services/tile-worker/`, and any other TS surface that needs to speak `GridFeature`, `Manifest`, or `LicenseSidecar`. It is the single point where schema drift between the data pipeline and the frontend gets caught — CI fails the build if generated types disagree with `platform/data/` Pydantic models.

The generation script lands in Phase 0 of the engineering brief. Until then, the contents of `src/index.ts` are a hand-written stub; do not extend by hand once the generator is in place.

See [`../../docs/MONOREPO.md`](../../docs/MONOREPO.md) for the cross-language seam rationale.
