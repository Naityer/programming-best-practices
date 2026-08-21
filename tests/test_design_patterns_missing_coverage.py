from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.detectors.behavioral import (  # noqa: E402
    detect_chain_of_responsibility,
    detect_iterator,
    detect_mediator,
    detect_memento,
    detect_template_method,
    detect_visitor,
)
from design_patterns.detectors.creational import (  # noqa: E402
    detect_abstract_factory,
    detect_factory_method,
)
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
    if limitations:
        raise AssertionError(limitations)
    return CodeGraph(unit.entities, relations, unit.discriminator_branches, frontend_level=frontend.level)


def assert_detected(test: unittest.TestCase, detector, source: str, pattern_id: str) -> None:
    hits = detector(build_graph(source))
    test.assertTrue(hits, pattern_id)
    test.assertTrue(any(result.pattern_id == pattern_id for _, result in hits))


class MissingCreationalCoverageTests(unittest.TestCase):
    def test_factory_method(self) -> None:
        assert_detected(self, detect_factory_method, """
            class Product:
                def render(self):
                    raise NotImplementedError
            class ConcreteProduct(Product):
                def render(self):
                    return "ok"
            class Creator:
                def create(self) -> Product:
                    return ConcreteProduct()
        """, "factory_method")

    def test_abstract_factory(self) -> None:
        assert_detected(self, detect_abstract_factory, """
            class AbstractFactory:
                def create_a(self):
                    raise NotImplementedError
                def create_b(self):
                    raise NotImplementedError
            class AbstractA:
                def use(self):
                    raise NotImplementedError
            class AbstractB:
                def use(self):
                    raise NotImplementedError
            class ConcreteA(AbstractA):
                def use(self):
                    return "a"
            class ConcreteB(AbstractB):
                def use(self):
                    return "b"
            class ConcreteFactory(AbstractFactory):
                def create_a(self) -> AbstractA:
                    return ConcreteA()
                def create_b(self) -> AbstractB:
                    return ConcreteB()
        """, "abstract_factory")


class MissingStructuralCoverageTests(unittest.TestCase):
    def test_bridge(self) -> None:
        assert_detected(self, detect_bridge, """
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
        """, "bridge")

    def test_composite(self) -> None:
        assert_detected(self, detect_composite, """
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
        """, "composite")

    def test_flyweight(self) -> None:
        assert_detected(self, detect_flyweight, """
            class Flyweight:
                pass
            class FlyweightFactory:
                def __init__(self):
                    self.cache = {}
                def get(self, key):
                    if key not in self.cache:
                        self.cache[key] = Flyweight()
                    return self.cache[key]
            class Context:
                def __init__(self, flyweight: Flyweight):
                    self.flyweight = flyweight
        """, "flyweight")


class MissingBehavioralCoverageTests(unittest.TestCase):
    def test_chain_of_responsibility(self) -> None:
        assert_detected(self, detect_chain_of_responsibility, """
            class Handler:
                def handle(self):
                    raise NotImplementedError
            class ConcreteHandler(Handler):
                def __init__(self, next_handler: Handler):
                    self.next_handler = next_handler
                def handle(self):
                    return self.next_handler.handle()
        """, "chain_of_responsibility")

    def test_iterator(self) -> None:
        assert_detected(self, detect_iterator, """
            class Cursor:
                def __init__(self, aggregate: Aggregate):
                    self.aggregate = aggregate
            class Aggregate:
                def iterator(self):
                    return Cursor(self)
        """, "iterator")

    def test_mediator(self) -> None:
        assert_detected(self, detect_mediator, """
            class Mediator:
                def __init__(self, left: Left, right: Right):
                    self.left = left
                    self.right = right
            class Left:
                def __init__(self, mediator: Mediator):
                    self.mediator = mediator
            class Right:
                def __init__(self, mediator: Mediator):
                    self.mediator = mediator
        """, "mediator")

    def test_memento(self) -> None:
        assert_detected(self, detect_memento, """
            class Memento:
                pass
            class Originator:
                def snapshot(self):
                    return Memento()
            class Caretaker:
                def __init__(self, snapshot: Memento):
                    self.snapshot = snapshot
        """, "memento")

    def test_template_method(self) -> None:
        assert_detected(self, detect_template_method, """
            class AbstractProcess:
                def run(self):
                    self.step_one()
                    self.step_two()
                def step_one(self):
                    raise NotImplementedError
                def step_two(self):
                    raise NotImplementedError
            class ConcreteProcess(AbstractProcess):
                def step_one(self):
                    return "one"
        """, "template_method")

    def test_visitor(self) -> None:
        assert_detected(self, detect_visitor, """
            class Visitor:
                def visit_first(self, element):
                    pass
                def visit_second(self, element):
                    pass
            class FirstElement:
                def accept(self, visitor: Visitor):
                    return visitor.visit_first(self)
            class SecondElement:
                def accept(self, visitor: Visitor):
                    return visitor.visit_second(self)
        """, "visitor")
