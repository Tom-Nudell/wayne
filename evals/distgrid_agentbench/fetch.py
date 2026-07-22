"""Fetch DistGrid-AgentBench at the pinned commit.

The upstream repo ships NO license file, so we never vendor its content into
the Wayne repo — this script clones it into a gitignored location at eval
time. Bump PIN deliberately; the pin is what makes eval runs comparable.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = "https://github.com/emmanuelbadmus/DistGrid-AgentBench.git"
PIN = "3d184adb2bd0b789b535c4bf6bbd1b7885a76fed"  # 2026-07-22


def fetch(dest: Path) -> Path:
    if (dest / "benchmark" / "tasks.jsonl").exists():
        head = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if head == PIN:
            print(f"already at pin: {dest}")
            return dest
        subprocess.run(["git", "-C", str(dest), "fetch", "origin", PIN], check=True)
        subprocess.run(["git", "-C", str(dest), "checkout", PIN], check=True)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", REPO, str(dest)], check=True)
    subprocess.run(["git", "-C", str(dest), "checkout", PIN], check=True)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    default = Path(os.environ.get("GRIDAGENT_DATA_ROOT", "data_root")) / "benchmarks" / "DistGrid-AgentBench"
    ap.add_argument("--dest", type=Path, default=default)
    args = ap.parse_args()
    fetch(args.dest)
    print(f"benchmark ready at {args.dest} (pin {PIN[:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
