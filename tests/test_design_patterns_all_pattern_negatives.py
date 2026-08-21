from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.catalog import load_catalog  # noqa: E402
from design_patterns.detectors import registry  # noqa: E402
from design_patterns.frontends.python import PythonFrontend  # noqa: E402
from design_patterns.ir import CodeGraph  # noqa: E402


def graph_for_name(name: str) -> CodeGraph:
    frontend = PythonFrontend()
    source = textwrap.dedent(f"""
        class {name}:
            pass
    """)
    unit = frontend.parse(source, Path("names_only.py"))
    relations, limitations = frontend.build_relations([unit])
    if limitations:
        raise AssertionError(limitations)
    return CodeGraph(unit.entities, relations, frontend_level=frontend.level)


class NamesNeverAssertPatternsTests(unittest.TestCase):
    """Specification §2/§29: a conventional class name is SUPPORTING-only
    and must never produce a design-pattern result by itself."""

    def test_all_catalog_names_are_negative_without_structure(self) -> None:
        detectors = registry()
        for spec in load_catalog():
            pattern_id = spec.id
            class_name = "Named" + "".join(part.title() for part in pattern_id.split("_"))
            hits = detectors[pattern_id](graph_for_name(class_name))
            self.assertEqual([], hits, pattern_id)
