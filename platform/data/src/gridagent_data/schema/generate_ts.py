"""Emit TS types from the Pydantic schema source of truth.

Run from the repo root:

    python -m gridagent_data.schema.generate_ts \\
        --out shared/schema/src/index.ts

Or in CI drift-check mode:

    python -m gridagent_data.schema.generate_ts \\
        --out shared/schema/src/index.ts --check

Drift mode exits 0 if the file on disk matches what would be generated,
2 if it doesn't, 1 on argparse errors.

The emitter is intentionally narrow — it only knows the type forms used
in :mod:`gridagent_data.schema.models`. Add a case here when a new form
is needed, rather than reaching for a general JSON-Schema-to-TS tool.
"""

from __future__ import annotations

import argparse
import sys
import types
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

from gridagent_data.schema import models as M


_HEADER = """// AUTO-GENERATED from platform/data/src/gridagent_data/schema/models.py
// DO NOT EDIT BY HAND. Regenerate with:
//
//   python -m gridagent_data.schema.generate_ts \\
//       --out shared/schema/src/index.ts
//
// CI fails the build if this file disagrees with the Python source.
//
// See docs/MONOREPO.md ("Cross-language seam") for rationale.

"""


def _ts_type(annotation: Any) -> str:
    """Render a Python type annotation as a TS type expression."""
    # Prefer named aliases over inline expansion when the value matches.
    if annotation in _ALIAS_BY_VALUE:
        return _ALIAS_BY_VALUE[annotation]

    origin = get_origin(annotation)
    args = get_args(annotation)

    if annotation is str:
        return "string"
    if annotation is int or annotation is float:
        return "number"
    if annotation is bool:
        return "boolean"
    if annotation is type(None):
        return "null"

    if origin is Literal:
        parts = [f"'{a}'" if isinstance(a, str) else repr(a) for a in args]
        return " | ".join(parts)

    if origin is Union or origin is types.UnionType:
        return " | ".join(_ts_type(a) for a in args)

    if origin in (tuple, list):
        # tuple[X, ...] or list[X] both render as readonly X[]
        if not args:
            inner = "unknown"
        else:
            inner = _ts_type(args[0])
        return f"readonly {inner}[]"

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation.__name__

    # Type aliases (e.g. FeatureKind = Literal[...]) — recognised by name
    # if they live in the models module.
    if hasattr(annotation, "__name__") and getattr(M, annotation.__name__, None) is annotation:
        return annotation.__name__

    raise TypeError(f"generate_ts: cannot render TS for {annotation!r}")


def _emit_literal_alias(name: str, alias: Any) -> str:
    args = get_args(alias)
    if not args:
        raise ValueError(f"{name} is not a Literal alias")
    parts = [f"'{a}'" if isinstance(a, str) else repr(a) for a in args]
    return f"export type {name} =\n  | " + "\n  | ".join(parts) + ";\n"


def _emit_model(model: type[BaseModel]) -> str:
    lines = [f"export interface {model.__name__} {{"]
    for name, field in model.model_fields.items():
        ts_t = _ts_type(field.annotation)
        opt = "?" if not field.is_required() else ""
        lines.append(f"  readonly {name}{opt}: {ts_t};")
    lines.append("}")
    return "\n".join(lines) + "\n"


# Order matters: aliases first so models can reference them, then models
# in dependency order (referenced models before referencing models).
_ALIASES: tuple[tuple[str, Any], ...] = (
    ("FeatureKind", M.FeatureKind),
    ("Tier", M.Tier),
)
_MODELS: tuple[type[BaseModel], ...] = (
    M.GridFeatureProperties,
    M.ManifestLayer,
    M.Manifest,
    M.LicenseSidecar,
)

# Lookup so model fields can render `kind: FeatureKind` instead of
# expanding the literal inline. Pydantic stores the resolved annotation,
# not the alias name, so we match by value equality.
_ALIAS_BY_VALUE = {alias: name for name, alias in _ALIASES}


def generate() -> str:
    parts: list[str] = [_HEADER]
    for name, alias in _ALIASES:
        parts.append(_emit_literal_alias(name, alias))
    parts.append("")
    for model in _MODELS:
        parts.append(_emit_model(model))
    return "\n".join(parts).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gridagent-schema-generate-ts")
    parser.add_argument("--out", type=Path, required=True, help="TS output path")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 2 if --out differs from what would be generated; do not write",
    )
    args = parser.parse_args(argv)

    generated = generate()

    if args.check:
        existing = args.out.read_text() if args.out.exists() else ""
        if existing != generated:
            print(
                f"schema drift: {args.out} disagrees with Pydantic source.\n"
                f"Run: python -m gridagent_data.schema.generate_ts --out {args.out}",
                file=sys.stderr,
            )
            return 2
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(generated)
    print(f"wrote {args.out} ({len(generated)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
