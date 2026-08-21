from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.detectors.creational import detect_abstract_factory, detect_factory_method  # noqa: E402
from design_patterns.frontends.python import PythonFrontend  # noqa: E402
from design_patterns.ir import CodeGraph  # noqa: E402


def build_graph(source: str) -> CodeGraph:
    frontend = PythonFrontend()
    unit = frontend.parse(textwrap.dedent(source), Path("fixture.py"))
    relations, limitations = frontend.build_relations([unit])
    if limitations:
        raise AssertionError(limitations)
    return CodeGraph(unit.entities, relations, unit.discriminator_branches, frontend_level=frontend.level)


class FactoryMethodVsAbstractFactoryTests(unittest.TestCase):
    def test_single_creation_point_is_factory_method_only(self) -> None:
        graph = build_graph("""
            class Product:
                def render(self):
                    raise NotImplementedError

            class ConcreteProduct(Product):
                def render(self):
                    return "ok"

            class Creator:
                def create(self) -> Product:
                    return ConcreteProduct()
        """)
        self.assertTrue(detect_factory_method(graph))
        self.assertEqual([], detect_abstract_factory(graph))

    def test_two_related_creation_points_are_abstract_factory_shape(self) -> None:
        graph = build_graph("""
            class AbstractFactory:
                def create_button(self):
                    raise NotImplementedError
                def create_menu(self):
                    raise NotImplementedError

            class AbstractButton:
                def draw(self):
                    raise NotImplementedError

            class AbstractMenu:
                def open(self):
                    raise NotImplementedError

            class ConcreteButton(AbstractButton):
                def draw(self):
                    return "button"

            class ConcreteMenu(AbstractMenu):
                def open(self):
                    return "menu"

            class ConcreteFactory(AbstractFactory):
                def create_button(self) -> AbstractButton:
                    return ConcreteButton()
                def create_menu(self) -> AbstractMenu:
                    return ConcreteMenu()
        """)
        self.assertTrue(detect_abstract_factory(graph))
        self.assertTrue(detect_factory_method(graph))
        hit = detect_abstract_factory(graph)[0][1]
        self.assertEqual("abstract_factory", hit.pattern_id)
        self.assertEqual("ConcreteFactory", hit.roles["concrete_factory"])
        self.assertEqual("AbstractFactory", hit.roles["abstract_factory"])
        self.assertEqual("medium", hit.confidence)


if __name__ == "__main__":
    unittest.main()
