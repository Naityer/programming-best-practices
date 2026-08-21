#!/usr/bin/env python3
"""Compatibility entrypoint for reporting.build_report."""

from reporting.build_report import *  # noqa: F403
from reporting.build_report import main as _main

if __name__ == "__main__":
    raise SystemExit(_main())