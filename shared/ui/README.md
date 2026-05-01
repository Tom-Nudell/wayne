# @wayne/ui

Design tokens, brand constants, base CSS, shared layout primitives.

Today this is tokens-only (`spacing`, `radius`, `type scale`, `motion`, `brand`). When `web/` grows shared layout components (header, paywall modal, attribution chip), they land in `src/components/` here only if they have 2+ consumers. Single-consumer components stay in `web/src/lib/`.

Mycelium palette colors live in [`@wayne/map`](../map) — this package is the *non-cartography* design surface.
