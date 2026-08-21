#!/usr/bin/env python3
"""Compatibility entrypoint for pipeline.run_audit."""

from pipeline.run_audit import *  # noqa: F403
from pipeline.run_audit import main as _main

if __name__ == "__main__":
    raise SystemExit(_main())