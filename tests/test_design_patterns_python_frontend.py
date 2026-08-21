from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.detectors.creational import detect_builder, detect_prototype, detect_singleton  # noqa: E402
from design_patterns.detectors.behavioral import detect_observer  # noqa: E402
from design_patterns.detectors.structural import detect_adapter, detect_decorator, detect_proxy  # noqa: E402
from design_patterns.frontends.python import PythonFrontend  # noqa: E402
from design_patterns.ir import CodeGraph  # noqa: E402


def build_graph(source: str, filename: str = "module.py"):
    frontend = PythonFrontend()
    unit = frontend.parse(textwrap.dedent(source), Path(filename))
    relations, limitations = frontend.build_relations([unit])
    graph = CodeGraph(unit.entities, relations, unit.discriminator_branches, frontend_level=frontend.level)
    return graph, limitations


class AdapterShapeTests(unittest.TestCase):
    SOURCE = """
        class Target:
            def request(self):
                raise NotImplementedError

        class Adaptee:
            def specific_request(self):
                return "legacy"

        class Adapter(Target):
            def __init__(self, adaptee: Adaptee):
                self._adaptee = adaptee

            def request(self):
                return self._adaptee.specific_request()
    """

    def test_detects_adapter_with_translated_method_name(self) -> None:
        graph, limitations = build_graph(self.SOURCE)
        self.assertEqual([], limitations)
        hits = detect_adapter(graph)
        self.assertEqual(1, len(hits))
        _, result = hits[0]
        self.assertEqual("detected", result.status)
        self.assertEqual("medium", result.confidence)  # Level B, all-HARD, 0 behavioral (this corte's ceiling)
        self.assertEqual({"target": "Target", "adapter": "Adapter", "adaptee": "Adaptee"}, result.roles)

    def test_does_not_also_fire_as_decorator_or_proxy(self) -> None:
        # different method name (request -> specific_request) rules those out
        graph, _ = build_graph(self.SOURCE)
        self.assertEqual([], detect_decorator(graph))
        self.assertEqual([], detect_proxy(graph))


class DecoratorProxyAmbiguityTests(unittest.TestCase):
    SOURCE = """
        class Service:
            def operation(self):
                raise NotImplementedError

        class RealService(Service):
            def operation(self):
                return "real"

        class ServiceWrapper(Service):
            def __init__(self, wrapped: RealService):
                self._wrapped = wrapped

            def operation(self):
                return self._wrapped.operation()
    """

    def test_same_method_name_delegation_fires_both_decorator_and_proxy(self) -> None:
        graph, _ = build_graph(self.SOURCE)
        decorator_hits = detect_decorator(graph)
        proxy_hits = detect_proxy(graph)
        self.assertEqual(1, len(decorator_hits))
        self.assertEqual(1, len(proxy_hits))
        self.assertEqual([], detect_adapter(graph))


class BuilderShapeTests(unittest.TestCase):
    SOURCE = """
        class Pizza:
            pass

        class PizzaBuilder:
            def __init__(self):
                self._cheese = False
                self._olives = False

            def add_cheese(self):
                self._cheese = True
                return self

            def add_olives(self):
                self._olives = True
                return self

            def build(self):
                return Pizza()
    """

    def test_detects_builder_via_chaining_and_terminal_instantiation(self) -> None:
        graph, _ = build_graph(self.SOURCE)
        hits = detect_builder(graph)
        self.assertEqual(1, len(hits))
        _, result = hits[0]
        self.assertEqual({"builder": "PizzaBuilder", "product": "Pizza"}, result.roles)


class SingletonShapeTests(unittest.TestCase):
    SOURCE = """
        class Registry:
            _instance = None

            @classmethod
            def instance(cls):
                if cls._instance is None:
                    cls._instance = Registry()
                return cls._instance
    """

    def test_singleton_needs_self_caching_not_just_a_name(self) -> None:
        # This is intentionally NOT detected: `cls._instance` isn't a
        # `self.<attr>` cache write, so it correctly produces no HARD
        # evidence rather than guessing from the method name "instance".
        graph, _ = build_graph(self.SOURCE)
        self.assertEqual([], detect_singleton(graph))

    def test_singleton_with_self_scoped_cache_is_detected(self) -> None:
        source = """
            class Registry:
                def __init__(self):
                    self._cache = {}

                def instance(self, key):
                    if key not in self._cache:
                        self._cache[key] = Registry()
                    return self._cache[key]
        """
        graph, _ = build_graph(source)
        hits = detect_singleton(graph)
        self.assertEqual(1, len(hits))


class PrototypeShapeTests(unittest.TestCase):
    def test_detects_self_class_clone(self) -> None:
        source = """
            class Shape:
                def clone(self):
                    return self.__class__()
        """
        graph, _ = build_graph(source)
        hits = detect_prototype(graph)
        self.assertEqual(1, len(hits))

    def test_no_clone_no_prototype(self) -> None:
        source = """
            class Shape:
                def area(self):
                    return 0
        """
        graph, _ = build_graph(source)
        self.assertEqual([], detect_prototype(graph))


class ObserverShapeTests(unittest.TestCase):
    SOURCE = """
        class EventBus:
            def __init__(self):
                self._subscribers = []

            def subscribe(self, subscriber):
                self._subscribers.append(subscriber)

            def publish(self, event):
                for subscriber in self._subscribers:
                    subscriber.handle(event)
    """

    def test_detects_fan_out_over_a_homogeneous_collection(self) -> None:
        graph, _ = build_graph(self.SOURCE)
        hits = detect_observer(graph)
        self.assertEqual(1, len(hits))
        _, result = hits[0]
        self.assertEqual("EventBus", result.roles["subject"])


class CrossFileLinkingTests(unittest.TestCase):
    def test_adapter_resolves_across_three_files(self) -> None:
        """spec §5.2/§17: Target, Adapter, Adaptee may live in different
        files; resolution must not require them in the same module."""
        frontend = PythonFrontend()
        units = [
            frontend.parse(
                "class PaymentGateway:\n    def pay(self):\n        raise NotImplementedError\n",
                Path("ports.py"),
            ),
            frontend.parse(
                "class LegacyGateway:\n    def charge(self):\n        return True\n",
                Path("legacy/client.py"),
            ),
            frontend.parse(
                textwrap.dedent("""
                    from ports import PaymentGateway
                    from legacy.client import LegacyGateway

                    class LegacyGatewayAdapter(PaymentGateway):
                        def __init__(self, legacy: LegacyGateway):
                            self._legacy = legacy

                        def pay(self):
                            return self._legacy.charge()
                """),
                Path("adapter.py"),
            ),
        ]
        relations, limitations = frontend.build_relations(units)
        entities = [e for unit in units for e in unit.entities]
        graph = CodeGraph(entities, relations, frontend_level=frontend.level)
        hits = detect_adapter(graph)
        self.assertEqual(1, len(hits), msg=f"limitations={limitations}")
        _, result = hits[0]
        self.assertEqual("adapter.py", result.primary_location.file)
        self.assertEqual(
            {"target": "PaymentGateway", "adapter": "LegacyGatewayAdapter", "adaptee": "LegacyGateway"},
            result.roles,
        )


if __name__ == "__main__":
    unittest.main()
