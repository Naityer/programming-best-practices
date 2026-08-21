from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.detectors.creational import detect_builder, detect_prototype, detect_singleton  # noqa: E402
from design_patterns.detectors.structural import (  # noqa: E402
    detect_adapter,
    detect_bridge,
    detect_composite,
    detect_facade,
    detect_flyweight,
)
from design_patterns.detectors.behavioral import detect_iterator, detect_strategy  # noqa: E402
from design_patterns.frontends.python import PythonFrontend  # noqa: E402
from design_patterns.ir import CodeGraph  # noqa: E402


def build_graph(source: str) -> CodeGraph:
    frontend = PythonFrontend()
    unit = frontend.parse(textwrap.dedent(source), Path("fixture.py"))
    relations, _ = frontend.build_relations([unit])
    return CodeGraph(unit.entities, relations, unit.discriminator_branches, frontend_level=frontend.level)


class StructuralCreationalLookalikesTests(unittest.TestCase):
    def test_builder_is_not_prototype(self) -> None:
        graph = build_graph("""
            class Product:
                pass
            class Builder:
                def set_name(self, name):
                    self.name = name
                    return self
                def set_size(self, size):
                    self.size = size
                    return self
                def build(self) -> Product:
                    return Product()
        """)
        self.assertTrue(detect_builder(graph))
        self.assertEqual([], detect_prototype(graph))

    def test_prototype_is_not_builder(self) -> None:
        graph = build_graph("""
            class Document:
                def clone(self):
                    return type(self)()
        """)
        self.assertTrue(detect_prototype(graph))
        self.assertEqual([], detect_builder(graph))

    def test_facade_is_not_adapter(self) -> None:
        graph = build_graph("""
            class Inventory:
                def reserve(self):
                    return True
            class Billing:
                def charge(self):
                    return True
            class OrderFacade:
                def __init__(self, inventory: Inventory, billing: Billing):
                    self.inventory = inventory
                    self.billing = billing
                def place(self):
                    self.inventory.reserve()
                    return self.billing.charge()
        """)
        self.assertTrue(detect_facade(graph))
        self.assertEqual([], detect_adapter(graph))

    def test_composite_is_not_iterator(self) -> None:
        graph = build_graph("""
            class Component:
                def operation(self):
                    raise NotImplementedError
            class Leaf(Component):
                def operation(self):
                    return "leaf"
            class Composite(Component):
                def __init__(self):
                    self.children = []
                def operation(self):
                    for child in self.children:
                        child.operation()
        """)
        self.assertTrue(detect_composite(graph))
        self.assertEqual([], detect_iterator(graph))

    def test_flyweight_is_not_singleton(self) -> None:
        graph = build_graph("""
            class Glyph:
                pass
            class GlyphFactory:
                def __init__(self):
                    self.cache = {}
                def get(self, key):
                    if key not in self.cache:
                        self.cache[key] = Glyph()
                    return self.cache[key]
            class Canvas:
                def __init__(self, glyph: Glyph):
                    self.glyph = glyph
        """)
        from design_patterns.detectors.structural import detect_flyweight
        self.assertTrue(detect_flyweight(graph))
        self.assertEqual([], detect_singleton(graph))

    def test_bridge_is_not_strategy(self) -> None:
        graph = build_graph("""
            class Implementor:
                def operation(self):
                    raise NotImplementedError
            class ImplementorA(Implementor):
                def operation(self):
                    return "a"
            class ImplementorB(Implementor):
                def operation(self):
                    return "b"
            class Abstraction:
                def __init__(self, implementor: Implementor):
                    self.implementor = implementor
                def operation(self):
                    return self.implementor.operation()
            class RefinedAbstraction(Abstraction):
                pass
        """)
        self.assertTrue(detect_bridge(graph))
        self.assertEqual([], detect_strategy(graph))


if __name__ == "__main__":
    unittest.main()
