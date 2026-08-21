from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.detectors.creational import detect_builder, detect_prototype, detect_singleton  # noqa: E402
from design_patterns.detectors.structural import (  # noqa: E402
    detect_bridge,
    detect_composite,
    detect_flyweight,
)
from design_patterns.frontends.python import PythonFrontend  # noqa: E402
from design_patterns.ir import CodeGraph  # noqa: E402


def build_graph(source: str) -> CodeGraph:
    frontend = PythonFrontend()
    unit = frontend.parse(textwrap.dedent(source), Path("fixture.py"))
    relations, limitations = frontend.build_relations([unit])
    return CodeGraph(unit.entities, relations, unit.discriminator_branches, frontend_level=frontend.level)


class CreationalPartialAndLookalikeTests(unittest.TestCase):
    def test_builder_without_terminal_product_is_withheld(self) -> None:
        graph = build_graph("""
            class QueryBuilder:
                def where(self, value):
                    return self
                def order_by(self, value):
                    return self
        """)
        self.assertEqual([], detect_builder(graph))

    def test_prototype_without_self_clone_is_withheld(self) -> None:
        graph = build_graph("""
            class Document:
                def copy_template(self, template):
                    return Document()
        """)
        self.assertEqual([], detect_prototype(graph))

    def test_cached_service_is_not_singleton(self) -> None:
        graph = build_graph("""
            class ServiceLocator:
                _cache = {}
                def get(self):
                    return self._cache.get("service")
        """)
        self.assertEqual([], detect_singleton(graph))


class StructuralPartialAndLookalikeTests(unittest.TestCase):
    def test_strategy_like_abstraction_without_refined_subclass_is_not_bridge(self) -> None:
        graph = build_graph("""
            class Renderer:
                def render(self):
                    raise NotImplementedError
            class SvgRenderer(Renderer):
                def render(self):
                    return "svg"
            class Screen:
                def __init__(self, renderer: Renderer):
                    self.renderer = renderer
                def draw(self):
                    return self.renderer.render()
        """)
        self.assertEqual([], detect_bridge(graph))

    def test_collection_without_common_component_contract_is_not_composite(self) -> None:
        graph = build_graph("""
            class Group:
                def __init__(self, values):
                    self.values = values
                def total(self):
                    return sum(self.values)
        """)
        self.assertEqual([], detect_composite(graph))

    def test_cache_without_shared_flyweight_context_is_withheld(self) -> None:
        graph = build_graph("""
            class ParserCache:
                _cache = {}
                def get(self, key):
                    if key not in self._cache:
                        self._cache[key] = object()
                    return self._cache[key]
        """)
        self.assertEqual([], detect_flyweight(graph))


if __name__ == "__main__":
    unittest.main()
