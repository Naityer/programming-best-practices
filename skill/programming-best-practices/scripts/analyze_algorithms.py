#!/usr/bin/env python3
"""Analyze source without importing or executing the audited project."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from algorithms import analyze_repository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("fast", "standard", "deep"), default="standard")
    parser.add_argument("--focus", action="append", default=[])
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--profiling-evidence", type=Path)
    parser.add_argument("--security-evidence", type=Path)
    args = parser.parse_args()
    try:
        profiling = json.loads(args.profiling_evidence.read_text(encoding="utf-8")) if args.profiling_evidence else None
        security = json.loads(args.security_evidence.read_text(encoding="utf-8")) if args.security_evidence else None
        result = analyze_repository(args.root, profile=args.profile, focus=set(args.focus) or None, cache_dir=args.cache_dir, use_cache=not args.no_cache, profiling_evidence=profiling, security_evidence=security)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
