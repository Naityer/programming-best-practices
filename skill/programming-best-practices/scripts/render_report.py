#!/usr/bin/env python3
"""Compatibility entrypoint for reporting.render_report."""

from reporting.render_report import *  # noqa: F403
from reporting.render_report import main as _main

if __name__ == "__main__":
    raise SystemExit(_main())