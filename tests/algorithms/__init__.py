"""Algorithm Intelligence tests and isolated product-package loader."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "skill" / "programming-best-practices" / "scripts"
_PACKAGE = _SCRIPTS / "algorithms"
_SPEC = importlib.util.spec_from_file_location(
    "pbp_algorithms_test_subject", _PACKAGE / "__init__.py",
    submodule_search_locations=[str(_PACKAGE)],
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load Algorithm Intelligence test subject")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
analyze_repository = _MODULE.analyze_repository

__all__ = ["analyze_repository"]