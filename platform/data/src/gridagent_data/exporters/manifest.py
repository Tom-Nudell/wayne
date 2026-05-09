"""Immutable manifest versioning for tile bundles (brief §5).

Every tile promotion writes a versioned manifest to the bundle directory.
The manifest records which layers are present, their feature counts, the
dataset version (YYYY-MM-DD), and a generation timestamp.

The frontend fetches ``/api/manifest`` on boot; the SvelteKit route reads
``latest.json`` and proxies it. Layer URLs in the manifest are relative so
the same manifest works for both R2 hosting and local dev.

Manifest shape
--------------
::

    {
      "version": "2026-05-08",
      "generated_at": "2026-05-08T12:00:00Z",
      "layers": [
        {
          "name": "transmission_lines",
          "kind": "transmission_line",
          "pmtiles": "transmission_lines.pmtiles",
          "feature_count": 229668,
          "license_spdx": ["ODbL-1.0"],
          "attribution_required": true
        },
        ...
      ]
    }

``latest.json`` is an alias that contains the full content of the most
recently approved version (not just a redirect). This keeps the frontend
free of a two-step fetch.

Human approval gate
-------------------
Manifests are *written* here but not *promoted* until the QA gate passes
and the caller explicitly calls ``approve_manifest(bundle_dir)``.
Unapproved bundles have ``"approved": false``; the promotion script
refuses to upload an unapproved manifest to R2.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _read_sidecars(bundle_dir: Path) -> list[dict]:
    """Collect license sidecar data for all layers in *bundle_dir*."""
    layers = []
    for sidecar in sorted(bundle_dir.glob("*.license.json")):
        try:
            doc = json.loads(sidecar.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        layers.append(
            {
                "name": doc.get("layer", sidecar.stem.removesuffix(".license")),
                "kind": doc.get("kind", ""),
                "pmtiles": doc.get("layer", sidecar.stem.removesuffix(".license")) + ".pmtiles",
                "feature_count": doc.get("feature_count", 0),
                "license_spdx": [lic["spdx"] for lic in doc.get("licenses", [])],
                "attribution_required": any(
                    lic.get("attribution_required", False)
                    for lic in doc.get("licenses", [])
                ),
            }
        )
    return layers


def write_manifest(
    bundle_dir: Path,
    *,
    version: str | None = None,
) -> Path:
    """Write ``manifest.json`` into *bundle_dir* and return the path.

    ``version`` defaults to today's date (``YYYY-MM-DD``). The manifest
    starts as unapproved; call ``approve_manifest(bundle_dir)`` after
    the QA gate passes to mark it ready for promotion.
    """
    bundle_dir = Path(bundle_dir)
    now = datetime.now(timezone.utc)
    ver = version or now.strftime("%Y-%m-%d")

    manifest = {
        "version": ver,
        "generated_at": now.isoformat(timespec="seconds"),
        "approved": False,
        "layers": _read_sidecars(bundle_dir),
    }
    manifest_path = bundle_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest_path


def approve_manifest(bundle_dir: Path) -> Path:
    """Mark the bundle's manifest as QA-approved and write ``latest.json``.

    Raises ``FileNotFoundError`` if no ``manifest.json`` exists.
    Raises ``ValueError`` if it is already approved (idempotency guard).

    ``latest.json`` gets the full manifest content — the frontend only
    ever reads one file.
    """
    bundle_dir = Path(bundle_dir)
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest.json in {bundle_dir}")

    manifest = json.loads(manifest_path.read_text())
    if manifest.get("approved"):
        # Allow re-approval (e.g. after a hotfix) by not raising here.
        pass
    manifest["approved"] = True
    manifest["approved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    manifest_path.write_text(json.dumps(manifest, indent=2))

    latest_path = bundle_dir / "latest.json"
    latest_path.write_text(json.dumps(manifest, indent=2))

    return latest_path


def read_manifest(bundle_dir: Path) -> dict:
    """Load ``manifest.json`` from *bundle_dir*.  Raises if missing."""
    p = Path(bundle_dir) / "manifest.json"
    if not p.exists():
        raise FileNotFoundError(f"No manifest.json in {bundle_dir}")
    return json.loads(p.read_text())
