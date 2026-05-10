#!/usr/bin/env bash
# Symlink the locally-generated PMTiles bundle into web/static/tiles/ so
# the SvelteKit dev server can serve it at /tiles/*.pmtiles. Idempotent.
#
# In production the same path resolves to the Cloudflare Worker / R2
# (see brief §4); this script is dev-only.
set -euo pipefail

WEB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$WEB_DIR/.." && pwd)"
SRC="$REPO_ROOT/data_root/bundle/snapshot_latest/tiles"
DST="$WEB_DIR/static/tiles"

if [ ! -d "$SRC" ]; then
  echo "error: $SRC does not exist." >&2
  echo "       run platform/data's bundle command first:" >&2
  echo "       cd $REPO_ROOT/platform/data && uv run python -m gridagent_data.cli bundle" >&2
  exit 1
fi

mkdir -p "$WEB_DIR/static"

if [ -L "$DST" ] && [ "$(readlink "$DST")" = "$SRC" ]; then
  echo "tiles symlink already up to date: $DST -> $SRC"
  exit 0
fi

if [ -e "$DST" ]; then
  echo "removing existing $DST"
  rm -rf "$DST"
fi

ln -s "$SRC" "$DST"
echo "linked $DST -> $SRC"
ls -1 "$DST" | sed 's/^/  /'
