from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.detectors.behavioral import (  # noqa: E402
    detect_state,
    detect_strategy,
    detect_template_method,
    detect_visitor,
)
from design_patterns.detectors.creational import detect_abstract_factory, detect_factory_method  # noqa: E402
from design_patterns.frontends.python import PythonFrontend  # noqa: E402
from design_patterns.ir import CodeGraph  # noqa: E402


def build_graph(source: str) -> CodeGraph:
    frontend = PythonFrontend()
    unit = frontend.parse(textwrap.dedent(source), Path("fixture.py"))
    relations, _ = frontend.build_relations([unit])
    return CodeGraph(unit.entities, relations, unit.discriminator_branches, frontend_level=frontend.level)


class RemainingCreationalEdgesTests(unittest.TestCase):
    def test_factory_method_without_product_abstraction_is_withheld(self) -> None:
        graph = build_graph("""
            class Creator:
                def create(self):
                    return object()
        """)
        self.assertEqual([], detect_factory_method(graph))

    def test_abstract_factory_with_one_product_method_is_withheld(self) -> None:
        graph = build_graph("""
            class Factory:
                def create(self):
                    raise NotImplementedError
            class ConcreteFactory(Factory):
                def create(self):
                    return object()
        """)
        self.assertEqual([], detect_abstract_factory(graph))


class StateStrategyEdgesTests(unittest.TestCase):
    def test_state_like_context_without_delegation_is_withheld(self) -> None:
        graph = build_graph("""
            class Mode:
                def run(self):
                    raise NotImplementedError
            class FastMode(Mode):
                def run(self):
                    return "fast"
            class SafeMode(Mode):
                def run(self):
                    return "safe"
            class Context:
                def __init__(self, mode: Mode):
                    self.mode = mode
        """)
        self.assertEqual([], detect_state(graph))
        self.assertEqual([], detect_strategy(graph))

    def test_strategy_requires_delegation_to_interchangeable_algorithm(self) -> None:
        graph = build_graph("""
            class Algorithm:
                def run(self):
                    raise NotImplementedError
            class FastAlgorithm(Algorithm):
                def run(self):
                    return "fast"
            class SafeAlgorithm(Algorithm):
                def run(self):
                    return "safe"
            class Context:
                def __init__(self, algorithm: Algorithm):
                    self.algorithm = algorithm
        """)
        self.assertEqual([], detect_strategy(graph))


class RemainingBehavioralEdgesTests(unittest.TestCase):
    def test_template_method_without_overriding_subclass_is_withheld(self) -> None:
        graph = build_graph("""
            class Process:
                def run(self):
                    self.step()
                def step(self):
                    raise NotImplementedError
        """)
        self.assertEqual([], detect_template_method(graph))

    def test_visitor_with_only_one_element_type_is_withheld(self) -> None:
        graph = build_graph("""
            class Visitor:
                def visit_first(self, element):
                    return element
            class First:
                def accept(self, visitor: Visitor):
                    return visitor.visit_first(self)
        """)
        self.assertEqual([], detect_visitor(graph))


if __name__ == "__main__":
    unittest.main()
