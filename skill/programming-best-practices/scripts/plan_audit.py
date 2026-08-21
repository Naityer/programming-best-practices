#!/usr/bin/env python3
"""Compatibility entrypoint for pipeline.plan_audit."""

from pipeline import plan_audit as _impl
from pipeline.plan_audit import *  # noqa: F403

# Preserve the historical monkeypatch surface: callers patching
# plan_audit.detect must still affect create_plan/main behind the wrapper.
detect = _impl.detect


def create_plan(*args, **kwargs):
    _impl.detect = detect
    return _impl.create_plan(*args, **kwargs)


def main() -> int:
    _impl.detect = detect
    return _impl.main()


if __name__ == "__main__":
    raise SystemExit(main())