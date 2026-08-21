"""spec §29's mandatory false-positive corpus — must "specifically prevent
the behavior currently observed in audit_code": `_detect_by_name` assigning
`Adapter 55%` to any class whose name ends in a known suffix, regardless of
structure. See design-patterns-module/00-prompt-inicial.md for the four real
`*Adapter` classes from the original screenshot this corpus exists to fix.
"""

from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

from tests.helpers import scripts_on_path

scripts_on_path()

from design_patterns.catalog import load_catalog  # noqa: E402
from design_patterns.detectors import registry  # noqa: E402
from design_patterns.detectors.behavioral import detect_state, detect_strategy  # noqa: E402
from design_patterns.detectors.structural import detect_adapter, detect_decorator, detect_proxy  # noqa: E402
from design_patterns.engine import run_engine  # noqa: E402
from design_patterns.frontends.python import PythonFrontend  # noqa: E402
from design_patterns.ir import CodeGraph  # noqa: E402


def build_graph(source: str, filename: str = "module.py"):
    frontend = PythonFrontend()
    unit = frontend.parse(textwrap.dedent(source), Path(filename))
    relations, _ = frontend.build_relations([unit])
    return CodeGraph(unit.entities, relations, unit.discriminator_branches, frontend_level=frontend.level)


def run_all(graph) -> list:
    """run_engine() returns (results, limitations) — the role-binding
    guardrail (Fase 3) needs somewhere to report a dropped pattern. Most
    tests here only care about the results."""
    results, _ = run_engine(graph, load_catalog(), registry())
    return results


class NameOnlyCorpusTests(unittest.TestCase):
    """The exact regression class from the original screenshot's shape: a
    name ending in a pattern suffix, zero structural evidence."""

    def test_class_named_adapter_without_adapter_behavior(self) -> None:
        graph = build_graph("""
            class DiagramDesignAdapter:
                def render(self):
                    return "svg"
        """)
        self.assertEqual([], detect_adapter(graph))
        self.assertEqual([], run_all(graph))

    def test_repository_without_repository_pattern(self) -> None:
        # "Repository" isn't one of the 22 GoF patterns this module detects
        # at all — the real assertion is that a bare class produces nothing.
        graph = build_graph("""
            class UserRepository:
                def get_name(self):
                    return "static"
        """)
        self.assertEqual([], run_all(graph))

    def test_provider_without_provider_structure(self) -> None:
        graph = build_graph("""
            class ConfigProvider:
                def get(self, key):
                    return None
        """)
        self.assertEqual([], run_all(graph))

    def test_a_class_with_no_bases_and_no_relations_never_becomes_a_hit_for_any_of_the_22_patterns(self) -> None:
        graph = build_graph("""
            class SignedLicenseAdapter:
                def __init__(self):
                    self.license = None

                def is_licensed(self):
                    return self.license is not None
        """)
        # This is the exact shape from the original screenshot: one field,
        # one method, ONE participant. An Adapter needs Target AND Adaptee —
        # a single-participant "Adapter" was already a contradiction in its
        # own terms, and it correctly produces nothing here.
        self.assertEqual([], run_all(graph))


class DecoratorLikeWrapperUsedAsProxyTests(unittest.TestCase):
    """spec §29: "Decorator-like wrapper used as Proxy -> Proxy / ambiguous,
    NO automatic Decorator." Same-method-name delegation is genuinely
    indistinguishable between Decorator and Proxy without behavioral evidence
    (spec §12) — the engine must merge them into one `ambiguous` result, not
    silently pick Decorator."""

    SOURCE = """
        class Service:
            def operation(self):
                raise NotImplementedError

        class RealService(Service):
            def operation(self):
                return "real"

        class CachingProxy(Service):
            def __init__(self, real: RealService):
                self._real = real

            def operation(self):
                return self._real.operation()
    """

    def test_engine_merges_into_ambiguous_not_an_automatic_decorator(self) -> None:
        graph = build_graph(self.SOURCE)
        results = run_all(graph)
        anchor_results = [r for r in results if "CachingProxy" in r.roles.values()]
        self.assertEqual(1, len(anchor_results), msg=f"expected exactly one merged result, got {results}")
        result = anchor_results[0]
        self.assertEqual("ambiguous", result.status)
        self.assertIn(result.pattern_id, {"decorator", "proxy"})
        contradiction_ids = {c.pattern_id for c in result.contradictions}
        self.assertTrue(contradiction_ids, "ambiguous result must name the competing pattern")
        self.assertNotEqual("detected", result.status)


class StrategyLikeStructureWithStateTransitionsTests(unittest.TestCase):
    """spec §29: "Strategy-like structure with state transitions -> State."""

    def test_transitions_between_concretes_classify_as_state_not_strategy(self) -> None:
        graph = build_graph("""
            class OrderState:
                def handle(self, order):
                    raise NotImplementedError

            class PendingState(OrderState):
                def handle(self, order):
                    return "pending"

            class RunningState(OrderState):
                def handle(self, order):
                    return "running"

            class Order:
                def __init__(self, state: OrderState):
                    self._state = state

                def process(self):
                    return self._state.handle(self)

                def advance(self):
                    self._state = RunningState()

                def reset(self):
                    self._state = PendingState()
        """)
        state_hits = detect_state(graph)
        strategy_hits = detect_strategy(graph)
        self.assertEqual([], strategy_hits)
        self.assertEqual(1, len(state_hits))
        _, result = state_hits[0]
        self.assertEqual("state", result.pattern_id)
        self.assertEqual("Order", result.roles["context"])

    def test_no_transitions_classifies_as_strategy_not_state(self) -> None:
        graph = build_graph("""
            class SortStrategy:
                def sort(self, items):
                    raise NotImplementedError

            class QuickSort(SortStrategy):
                def sort(self, items):
                    return sorted(items)

            class BubbleSort(SortStrategy):
                def sort(self, items):
                    return sorted(items)

            class Sorter:
                def __init__(self, strategy: SortStrategy):
                    self._strategy = strategy

                def run(self, items):
                    return self._strategy.sort(items)
        """)
        strategy_hits = detect_strategy(graph)
        state_hits = detect_state(graph)
        self.assertEqual([], state_hits)
        self.assertEqual(1, len(strategy_hits))
        _, result = strategy_hits[0]
        self.assertEqual("strategy", result.pattern_id)
        self.assertEqual("Sorter", result.roles["context"])


if __name__ == "__main__":
    unittest.main()
