from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.detectors.structural import detect_decorator, detect_facade, detect_proxy  # noqa: E402
from design_patterns.frontends.python import PythonFrontend  # noqa: E402
from design_patterns.ir import CodeGraph  # noqa: E402


def build_graph(source: str) -> CodeGraph:
    frontend = PythonFrontend()
    unit = frontend.parse(textwrap.dedent(source), Path("fixture.py"))
    relations, _ = frontend.build_relations([unit])
    return CodeGraph(unit.entities, relations, unit.discriminator_branches, frontend_level=frontend.level)


class FinalPartialCoverageTests(unittest.TestCase):
    def test_facade_with_one_subsystem_is_withheld(self) -> None:
        graph = build_graph("""
            class Inventory:
                def reserve(self):
                    return True
            class Facade:
                def __init__(self, inventory: Inventory):
                    self.inventory = inventory
                def reserve(self):
                    return self.inventory.reserve()
        """)
        self.assertEqual([], detect_facade(graph))

    def test_decorator_without_wrapped_component_is_withheld(self) -> None:
        graph = build_graph("""
            class Component:
                def operation(self):
                    raise NotImplementedError
            class Decorator(Component):
                def operation(self):
                    return "extra"
        """)
        self.assertEqual([], detect_decorator(graph))

    def test_proxy_without_real_subject_is_withheld(self) -> None:
        graph = build_graph("""
            class Subject:
                def request(self):
                    raise NotImplementedError
            class Proxy(Subject):
                def request(self):
                    return "denied"
        """)
        self.assertEqual([], detect_proxy(graph))


if __name__ == "__main__":
    unittest.main()
