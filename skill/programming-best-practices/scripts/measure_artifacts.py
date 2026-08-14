#!/usr/bin/env python3
"""Measure build output size, deterministically and without dependencies.

    python scripts/measure_artifacts.py --root <repo> --dir dist --output sizes.json

Emits the `bundle-size` document consumed by `normalize_tool_output.py`:

    {"schema_version": "1.0.0", "tool": "bundle-size", "root": "dist",
     "total_bytes": 123, "file_count": 4,
     "by_extension": {".js": {"bytes": 100, "count": 2}, ...},
     "largest": [{"path": "assets/index-abc.js", "bytes": 90}, ...]}

Why a script and not a shell one-liner: the plan is data, never a shell string
(`run_audit.py` executes `argv` with `shell=False`), so anything that needs to
walk a tree and aggregate has to be a program. Stdlib only, like every other
script here.

Sizes are reported, never judged. This script has no notion of "too big" — a
budget that nobody agreed to is exactly the invented threshold `SKILL.md`
forbids. Regressions come from comparing against a recorded baseline, which is
`compare_perf_baseline.py`'s job.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Ruido de compilación que no viaja al usuario y solo añade varianza.
IGNORED_NAMES = {".DS_Store", "Thumbs.db"}
IGNORED_SUFFIXES = {".map"}


def measure(target: Path, root: Path) -> dict[str, Any]:
    by_extension: dict[str, dict[str, int]] = {}
    files: list[tuple[str, int]] = []
    total = 0

    for path in sorted(target.rglob("*")):
        if not path.is_file() or path.name in IGNORED_NAMES:
            continue
        if path.suffix in IGNORED_SUFFIXES:
            continue
        size = path.stat().st_size
        total += size
        rel = path.relative_to(target).as_posix()
        files.append((rel, size))
        bucket = by_extension.setdefault(path.suffix or "(sin extensión)", {"bytes": 0, "count": 0})
        bucket["bytes"] += size
        bucket["count"] += 1

    files.sort(key=lambda item: (-item[1], item[0]))
    return {
        "schema_version": "1.0.0",
        "tool": "bundle-size",
        "root": target.relative_to(root).as_posix() if target.is_relative_to(root) else str(target),
        "total_bytes": total,
        "file_count": len(files),
        "by_extension": dict(sorted(by_extension.items())),
        "largest": [{"path": rel, "bytes": size} for rel, size in files[:15]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Repository root")
    parser.add_argument("--dir", dest="directory", required=True,
                        help="Build output directory, relative to --root")
    parser.add_argument("--output", type=Path, help="Write the document here as well")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    target = (root / args.directory).resolve()
    # El directorio de salida tiene que estar DENTRO del repo: sin esto un
    # `--dir ../../..` mediría cualquier punto del disco.
    if not target.is_relative_to(root):
        raise SystemExit(f"output directory escapes the repository: {target}")
    if not target.is_dir():
        raise SystemExit(f"build output directory not found: {target}")

    document = measure(target, root)
    text = json.dumps(document, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
