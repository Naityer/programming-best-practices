"""One detector module per catalog family (spec §4/§11): creational.py,
structural.py, behavioral.py. `registry()` collects every pattern_id -> Detector
mapping so analyze_design_patterns.py doesn't need to know the family split.
"""

from __future__ import annotations

from ..engine import Detector
from . import behavioral, creational, structural


def registry() -> dict[str, Detector]:
    reg: dict[str, Detector] = {}
    reg.update(creational.DETECTORS)
    reg.update(structural.DETECTORS)
    reg.update(behavioral.DETECTORS)
    return reg
