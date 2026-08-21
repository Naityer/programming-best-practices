#!/usr/bin/env python3
"""Compatibility entrypoint for reporting.normalize_tool_output."""

from reporting.normalize_tool_output import *  # noqa: F403
from reporting.normalize_tool_output import main as _main

if __name__ == "__main__":
    raise SystemExit(_main())